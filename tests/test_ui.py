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
        self.calls = 0

    def recognize(self, sample: RecognitionSample) -> RecognitionResult:
        self.calls += 1
        if self.fail:
            raise RecognitionError("UI test failure")
        return RecognitionResult("ink", "ui-fake", 1.0)


def add_stroke(window: MainWindow) -> None:
    window.canvas.buffer.begin(Point(0.1, 0.2, 1, 10, 20))
    window.canvas.buffer.end(Point(0.7, 0.8, 2, 70, 80))


def test_empty_commits_insert_plain_terminators(qtbot) -> None:
    service = HandwritingService(UiRecognizer(), InkRenderer(), None)
    window = MainWindow(Settings(save_samples=False, autosave_enabled=False), service)
    qtbot.addWidget(window)
    window._request_commit(" ")
    window._request_commit("\n")
    assert window.editor.toPlainText() == "\n"


def test_async_commit_and_undo_restore_ink(qtbot) -> None:
    service = HandwritingService(UiRecognizer(), InkRenderer(), None)
    window = MainWindow(Settings(save_samples=False, autosave_enabled=False), service)
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
    window = MainWindow(Settings(save_samples=False, autosave_enabled=False), service)
    qtbot.addWidget(window)
    add_stroke(window)
    window._request_commit(" ")
    qtbot.waitUntil(lambda: not window._recognition_pending, timeout=3000)
    assert len(window.canvas.strokes) == 1
    assert "ink preserved" in window.statusBar().currentMessage()


def test_clear_then_undo_restores_word(qtbot) -> None:
    service = HandwritingService(UiRecognizer(), InkRenderer(), None)
    window = MainWindow(Settings(save_samples=False, autosave_enabled=False), service)
    qtbot.addWidget(window)
    add_stroke(window)
    window._clear_ink()
    assert window.canvas.buffer.is_empty
    window._undo()
    assert len(window.canvas.strokes) == 1


def test_enter_commits_word_then_switches_line_for_next_handwriting(qtbot) -> None:
    recognizer = UiRecognizer()
    service = HandwritingService(recognizer, InkRenderer(), None)
    settings = Settings(save_samples=False, autosave_enabled=False)
    window = MainWindow(settings, service)
    qtbot.addWidget(window)
    add_stroke(window)
    window._request_commit("\n")
    qtbot.waitUntil(lambda: window.editor.toPlainText() == "ink\n", timeout=3000)
    assert window.document.current_line_index == 1

    add_stroke(window)
    window._request_commit(" ")
    qtbot.waitUntil(lambda: window.editor.toPlainText() == "ink\nink ", timeout=3000)
    assert [len(line.words) for line in window.document.lines] == [1, 1]


def test_preview_is_debounced_and_never_committed(qtbot) -> None:
    recognizer = UiRecognizer()
    service = HandwritingService(recognizer, InkRenderer(), None)
    settings = Settings(
        save_samples=False,
        autosave_enabled=False,
        preview_debounce_ms=80,
    )
    window = MainWindow(settings, service)
    qtbot.addWidget(window)
    add_stroke(window)
    window.canvas.ink_changed.emit()
    qtbot.wait(30)
    assert recognizer.calls == 0
    qtbot.waitUntil(lambda: recognizer.calls == 1, timeout=1000)
    qtbot.waitUntil(lambda: window.canvas.preview_text == "ink", timeout=1000)
    assert window.editor.toPlainText() == ""
