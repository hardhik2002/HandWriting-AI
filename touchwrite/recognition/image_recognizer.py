"""Lazy, process-cached TrOCR word recognizer."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image

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

    def __init__(
        self,
        model_name: str,
        device: str = "auto",
        beam_width: int = 8,
        max_new_tokens: int = 24,
        processor_use_fast: bool = False,
        debug_dir: Path | None = None,
    ) -> None:
        self.model_name = model_name
        self.requested_device = device
        self.beam_width = beam_width
        self.max_new_tokens = max_new_tokens
        self.processor_use_fast = processor_use_fast
        self.debug_dir = debug_dir
        self._device = "cpu"
        self._processor: Any = None
        self._model: Any = None
        self._load_lock = threading.Lock()
        self._model_load_duration_ms: float | None = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            try:
                import torch
                from transformers import TrOCRProcessor, VisionEncoderDecoderModel

                started = time.perf_counter()
                self._device = self._select_device(torch)
                LOGGER.info("loading recognition model=%s device=%s", self.model_name, self._device)
                self._processor = TrOCRProcessor.from_pretrained(
                    self.model_name, use_fast=self.processor_use_fast
                )
                self._model = VisionEncoderDecoderModel.from_pretrained(self.model_name)
                self._model.to(self._device)
                self._model.eval()
                self._model_load_duration_ms = (time.perf_counter() - started) * 1000
                LOGGER.info(
                    "recognition model loaded duration_ms=%.1f processor=%s",
                    self._model_load_duration_ms,
                    type(self._processor.image_processor).__name__,
                )
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
            processing_started = time.perf_counter()
            pixel_values = self._processor(images=image, return_tensors="pt").pixel_values
            pixel_values = pixel_values.to(self._device)
            processing_duration = (time.perf_counter() - processing_started) * 1000
            if self.debug_dir is not None:
                self._save_model_input(sample, pixel_values)
            generation_settings = {
                "num_beams": self.beam_width,
                "num_return_sequences": self.beam_width,
                "max_new_tokens": self.max_new_tokens,
                "early_stopping": self.beam_width > 1,
                "do_sample": False,
                "length_penalty": 1.0,
            }
            generation_started = time.perf_counter()
            with torch.inference_mode():
                sequences = self._model.generate(
                    pixel_values,
                    **generation_settings,
                )
            generation_duration = (time.perf_counter() - generation_started) * 1000
            decoding_started = time.perf_counter()
            decoded = self._processor.batch_decode(sequences, skip_special_tokens=True)
            unique = tuple(dict.fromkeys(text.strip() for text in decoded if text.strip()))
            decoding_duration = (time.perf_counter() - decoding_started) * 1000
            if not unique:
                raise RecognitionError("model returned no text")
            selected = select_single_word_candidate(unique)
            duration = (time.perf_counter() - started) * 1000
            LOGGER.info(
                "recognition result=%r raw=%r total_ms=%.1f processor_ms=%.1f "
                "generate_ms=%.1f decode_ms=%.1f",
                selected,
                unique[0],
                duration,
                processing_duration,
                generation_duration,
                decoding_duration,
            )
            return RecognitionResult(
                text=selected,
                raw_text=unique[0],
                confidence=None,
                model_name=self.model_name,
                inference_duration_ms=duration,
                alternatives=tuple(
                    RecognitionCandidate(text) for text in unique if text != selected
                ),
                model_load_duration_ms=self._model_load_duration_ms,
                processing_duration_ms=processing_duration,
                generation_duration_ms=generation_duration,
                decoding_duration_ms=decoding_duration,
                device=self._device,
                processor_mode=type(self._processor.image_processor).__name__,
                generation_settings=generation_settings,
            )
        except RecognitionError:
            raise
        except Exception as error:
            raise RecognitionError(f"inference failed: {error}") from error

    def _save_model_input(self, sample: RecognitionSample, pixel_values: Any) -> None:
        import torch

        sample_dir = self.debug_dir / sample.word.word_id
        sample_dir.mkdir(parents=True, exist_ok=True)
        tensor = pixel_values[0].detach().cpu()
        image_processor = self._processor.image_processor
        mean = torch.tensor(image_processor.image_mean).view(-1, 1, 1)
        std = torch.tensor(image_processor.image_std).view(-1, 1, 1)
        restored = ((tensor * std + mean).clamp(0, 1) * 255).to(torch.uint8)
        array = restored.permute(1, 2, 0).numpy()
        Image.fromarray(array).save(sample_dir / "model_input.png")
        (sample_dir / "model_input.json").write_text(
            json.dumps(
                {
                    "source_mode": sample.image.mode,
                    "source_size": list(sample.image.size),
                    "tensor_shape": list(pixel_values.shape),
                    "tensor_min": float(pixel_values.min().item()),
                    "tensor_max": float(pixel_values.max().item()),
                    "processor": type(image_processor).__name__,
                    "use_fast_requested": self.processor_use_fast,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def is_single_word_candidate(text: str) -> bool:
    """Accept one model-produced token, including internal apostrophes or hyphens."""
    if not text or any(character.isspace() for character in text):
        return False
    if not text[0].isalnum() or not text[-1].isalnum():
        return False
    return all(character.isalnum() or character in {"'", "-"} for character in text)


def select_single_word_candidate(candidates: tuple[str, ...]) -> str:
    """Use explicit word segmentation to prefer a clean beam without changing its characters."""
    return next((text for text in candidates if is_single_word_candidate(text)), candidates[0])
