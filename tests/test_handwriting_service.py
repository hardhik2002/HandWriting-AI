from __future__ import annotations

import json

import pytest
from PIL import Image

from tests.helpers import stroke
from touchwrite.ink.models import HandwrittenWord
from touchwrite.ink.renderer import InkRenderer
from touchwrite.persistence.session_store import SessionStore
from touchwrite.recognition.base import (
    HandwritingRecognizer,
    RecognitionError,
    RecognitionResult,
    RecognitionSample,
)
from touchwrite.services.handwriting_service import HandwritingService


class FakeRecognizer(HandwritingRecognizer):
    def __init__(self, fails: bool = False) -> None:
        self.fails = fails

    def recognize(self, sample: RecognitionSample) -> RecognitionResult:
        assert isinstance(sample.image, Image.Image)
        if self.fails:
            raise RecognitionError("test failure")
        return RecognitionResult("hello", "fake", 3.5, confidence=None, raw_text=" hello ")


def test_commit_word_with_space_and_persistence(tmp_path) -> None:
    word = HandwrittenWord([stroke()])
    service = HandwritingService(FakeRecognizer(), InkRenderer(), SessionStore(tmp_path))
    outcome = service.commit(word, " ")
    assert outcome.inserted_text == "hello "
    assert outcome.word.raw_prediction == " hello "
    assert (tmp_path / word.word_id / "processed.png").exists()


def test_commit_word_with_newline() -> None:
    service = HandwritingService(FakeRecognizer(), InkRenderer(), None)
    outcome = service.commit(HandwrittenWord([stroke()]), "\n")
    assert outcome.inserted_text == "hello\n"


def test_failure_does_not_mutate_prediction() -> None:
    word = HandwrittenWord([stroke()])
    service = HandwritingService(FakeRecognizer(fails=True), InkRenderer(), None)
    with pytest.raises(RecognitionError, match="test failure"):
        service.commit(word, " ")
    assert word.predicted_text is None


def test_debug_mode_saves_pre_model_artifacts(tmp_path) -> None:
    debug_dir = tmp_path / "debug"
    word = HandwrittenWord([stroke()])
    service = HandwritingService(
        FakeRecognizer(), InkRenderer(), None, debug_dir=debug_dir
    )
    service.commit(word, " ")
    sample_dir = debug_dir / word.word_id
    assert {path.name for path in sample_dir.iterdir()} == {
        "raw_strokes.png",
        "rendered.png",
        "processed.png",
        "preprocessing.json",
    }


def test_touchscreen_debug_saves_separate_coordinate_spaces(tmp_path) -> None:
    debug_dir = tmp_path / "touchscreen"
    word = HandwrittenWord([stroke()])
    word.recognition_metadata["input_mode"] = "touchscreen"
    service = HandwritingService(
        FakeRecognizer(), InkRenderer(), None, debug_dir=debug_dir
    )
    service.commit(word, " ")
    sample_dir = debug_dir / word.word_id
    assert {
        "capture.json",
        "display.json",
        "recognition.json",
        "raw.png",
        "processed.png",
    } <= {path.name for path in sample_dir.iterdir()}
    capture = json.loads((sample_dir / "capture.json").read_text(encoding="utf-8"))
    display = json.loads((sample_dir / "display.json").read_text(encoding="utf-8"))
    recognition = json.loads(
        (sample_dir / "recognition.json").read_text(encoding="utf-8")
    )
    assert capture["aspect_ratio"] == display["aspect_ratio"]
    assert recognition["aspect_ratio"] == capture["aspect_ratio"]
