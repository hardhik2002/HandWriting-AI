from __future__ import annotations

from touchwrite.config.settings import Settings
from touchwrite.ink.models import Point
from touchwrite.ink.renderer import InkRenderer
from touchwrite.recognition.base import (
    HandwritingRecognizer,
    RecognitionError,
    RecognitionResult,
    RecognitionSample,
)
from touchwrite.services.handwriting_service import HandwritingService
from touchwrite.ui.main_window import MainWindow


class UiRecognizer(HandwritingRecognizer):
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def recognize(self, sample: RecognitionSample) -> RecognitionResult:
        if self.fail:
            raise RecognitionError("UI test failure")
        return RecognitionResult("ink", "ui-fake", 1.0)


def add_stroke(window: MainWindow) -> None:
    window.canvas.buffer.begin(Point(0.1, 0.2, 1, 10, 20))
    window.canvas.buffer.end(Point(0.7, 0.8, 2, 70, 80))


def test_empty_commits_insert_plain_terminators(qtbot) -> None:
    service = HandwritingService(UiRecognizer(), InkRenderer(), None)
    window = MainWindow(Settings(save_samples=False), service)
    qtbot.addWidget(window)
    window._request_commit(" ")
    window._request_commit("\n")
    assert window.editor.toPlainText() == " \n"


def test_async_commit_and_undo_restore_ink(qtbot) -> None:
    service = HandwritingService(UiRecognizer(), InkRenderer(), None)
    window = MainWindow(Settings(save_samples=False), service)
    qtbot.addWidget(window)
    add_stroke(window)
    window._request_commit(" ")
    qtbot.waitUntil(lambda: window.editor.toPlainText() == "ink ", timeout=3000)
    assert window.canvas.buffer.is_empty
    window._undo()
    assert window.editor.toPlainText() == ""
    assert len(window.canvas.strokes) == 1


def test_recognition_failure_preserves_ink(qtbot) -> None:
    service = HandwritingService(UiRecognizer(fail=True), InkRenderer(), None)
    window = MainWindow(Settings(save_samples=False), service)
    qtbot.addWidget(window)
    add_stroke(window)
    window._request_commit(" ")
    qtbot.waitUntil(lambda: not window._recognition_pending, timeout=3000)
    assert len(window.canvas.strokes) == 1
    assert "ink preserved" in window.statusBar().currentMessage()
