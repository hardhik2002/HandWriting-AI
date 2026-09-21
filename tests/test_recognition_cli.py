from __future__ import annotations

from PIL import Image

from touchwrite.recognition.base import RecognitionCandidate, RecognitionResult
from touchwrite.tools import test_recognition


class FakeDiagnosticRecognizer:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def recognize(self, sample) -> RecognitionResult:
        assert sample.image.mode == "RGB"
        return RecognitionResult(
            text="hardhik",
            raw_text="hardhi K",
            model_name=self.kwargs["model_name"],
            inference_duration_ms=12.0,
            alternatives=(RecognitionCandidate("hardhi K"),),
            model_load_duration_ms=100.0,
            processing_duration_ms=2.0,
            generation_duration_ms=9.0,
            decoding_duration_ms=1.0,
            device="cpu",
            processor_mode="ViTImageProcessor",
            generation_settings={"do_sample": False},
        )


def test_direct_recognition_tool_bypasses_gui(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "word.png"
    Image.new("L", (512, 128), 255).save(image_path)
    monkeypatch.setattr(test_recognition, "ImageHandwritingRecognizer", FakeDiagnosticRecognizer)
    result = test_recognition.run_diagnostic(
        image_path,
        model_name="test/model",
        device="cpu",
        processor_use_fast=False,
        beam_width=8,
        max_new_tokens=24,
    )
    assert result["selected_prediction"] == "hardhik"
    assert result["raw_prediction"] == "hardhi K"
    assert result["generation_settings"] == {"do_sample": False}
