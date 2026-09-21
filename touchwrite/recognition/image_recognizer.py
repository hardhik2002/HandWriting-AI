"""Lazy, process-cached TrOCR word recognizer."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from touchwrite.recognition.base import (
    HandwritingRecognizer,
    RecognitionCandidate,
    RecognitionError,
    RecognitionResult,
    RecognitionSample,
)

LOGGER = logging.getLogger(__name__)


class ImageHandwritingRecognizer(HandwritingRecognizer):
    """Hugging Face VisionEncoderDecoderModel adapter.

    The model is loaded once, on first recognition. Reported confidence remains ``None`` because
    beam sequence scores are model-ranking scores, not calibrated probabilities.
    """

    def __init__(self, model_name: str, device: str = "auto", beam_width: int = 4) -> None:
        self.model_name = model_name
        self.requested_device = device
        self.beam_width = beam_width
        self._device = "cpu"
        self._processor: Any = None
        self._model: Any = None
        self._load_lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            try:
                import torch
                from transformers import TrOCRProcessor, VisionEncoderDecoderModel

                self._device = self._select_device(torch)
                LOGGER.info("loading recognition model=%s device=%s", self.model_name, self._device)
                self._processor = TrOCRProcessor.from_pretrained(self.model_name)
                self._model = VisionEncoderDecoderModel.from_pretrained(self.model_name)
                self._model.to(self._device)
                self._model.eval()
                LOGGER.info("recognition model loaded")
            except Exception as error:
                self._model = None
                self._processor = None
                message = f"could not load model {self.model_name}: {error}"
                raise RecognitionError(message) from error

    def _select_device(self, torch_module: Any) -> str:
        requested = self.requested_device.lower()
        if requested != "auto":
            if requested == "cuda" and not torch_module.cuda.is_available():
                LOGGER.warning("CUDA requested but unavailable; using CPU")
                return "cpu"
            return requested
        return "cuda" if torch_module.cuda.is_available() else "cpu"

    def recognize(self, sample: RecognitionSample) -> RecognitionResult:
        self._ensure_loaded()
        try:
            import torch

            started = time.perf_counter()
            image = sample.image.convert("RGB")
            pixel_values = self._processor(images=image, return_tensors="pt").pixel_values
            pixel_values = pixel_values.to(self._device)
            with torch.inference_mode():
                sequences = self._model.generate(
                    pixel_values,
                    num_beams=self.beam_width,
                    num_return_sequences=self.beam_width,
                    max_new_tokens=64,
                    early_stopping=True,
                )
            decoded = self._processor.batch_decode(sequences, skip_special_tokens=True)
            unique = tuple(dict.fromkeys(text.strip() for text in decoded if text.strip()))
            if not unique:
                raise RecognitionError("model returned no text")
            duration = (time.perf_counter() - started) * 1000
            LOGGER.info("recognition result=%r duration_ms=%.1f", unique[0], duration)
            return RecognitionResult(
                text=unique[0],
                raw_text=unique[0],
                confidence=None,
                model_name=self.model_name,
                inference_duration_ms=duration,
                alternatives=tuple(RecognitionCandidate(text) for text in unique[1:]),
            )
        except RecognitionError:
            raise
        except Exception as error:
            raise RecognitionError(f"inference failed: {error}") from error
