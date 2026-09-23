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
        self.samples: list[RecognitionSample] = []

    def recognize(self, sample: RecognitionSample) -> RecognitionResult:
        self.calls += 1
        self.samples.append(sample)
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


def test_touch_toolbar_actions_are_visible_and_canvas_starts_below_them(qtbot) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QToolBar

    service = HandwritingService(UiRecognizer(), InkRenderer(), None)
    window = MainWindow(
        Settings(save_samples=False, autosave_enabled=False, auto_detect_input=False),
        service,
    )
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    actions_toolbar = window.findChild(QToolBar, "actionsToolbar")
    assert actions_toolbar is not None
    required = {
        "Undo",
        "Redo",
        "Clear Ink",
        "Commit / Space",
        "New Line",
        "Save",
        "Export",
        "Settings",
        "Diagnostics",
    }
    actions = {action.text(): action for action in actions_toolbar.actions()}
    assert required <= actions.keys()
    for label in required:
        button = actions_toolbar.widgetForAction(actions[label])
        assert button is not None
        assert button.minimumSizeHint().height() >= 44
        assert button.isVisible()
    toolbar_bottom = actions_toolbar.mapTo(window, QPoint(0, actions_toolbar.height())).y()
    canvas_top = window.canvas.mapTo(window, QPoint(0, 0)).y()
    assert canvas_top >= toolbar_bottom
    assert [window.input_mode_combo.itemText(index) for index in range(3)] == [
        "Touch Screen",
        "Precision Touchpad",
        "Mouse",
    ]
    window.resize(900, 620)
    qtbot.waitUntil(window.more_button.isVisible)
    assert {action.text() for action in window.more_menu.actions()} >= {
        "Save",
        "Export",
        "Settings",
        "Diagnostics",
    }


def test_commit_during_active_stroke_waits_for_native_end(qtbot) -> None:
    recognizer = UiRecognizer()
    service = HandwritingService(recognizer, InkRenderer(), None)
    window = MainWindow(
        Settings(save_samples=False, autosave_enabled=False, auto_detect_input=False),
        service,
    )
    qtbot.addWidget(window)
    window.canvas.buffer.begin(Point(0.1, 0.2, 1, 10, 20))
    window._request_commit(" ")
    assert recognizer.calls == 0
    assert window._pending_commit_terminator == " "

    window.canvas.buffer.end(Point(0.7, 0.8, 2, 70, 80))
    window.canvas.ink_changed.emit()
    window.canvas.stroke_ended.emit()
    qtbot.waitUntil(lambda: window.editor.toPlainText() == "ink ", timeout=3000)
    assert len(recognizer.samples) == 1
    assert len(recognizer.samples[0].word.strokes[0].points) == 2
    events = [record["event"] for record in window.recognition_timeline.records]
    assert events.index("commit_pressed") < events.index("stroke_ended")
    assert events.index("stroke_ended") < events.index("commit_snapshot_created")
    assert events.index("commit_snapshot_created") < events.index("commit_finished")


def test_rapid_space_boundary_does_not_leak_strokes_between_words(qtbot) -> None:
    recognizer = UiRecognizer()
    service = HandwritingService(recognizer, InkRenderer(), None)
    window = MainWindow(
        Settings(save_samples=False, autosave_enabled=False, auto_detect_input=False),
        service,
    )
    qtbot.addWidget(window)
    add_stroke(window)
    window._request_commit(" ")
    add_stroke(window)
    window._request_commit(" ")
    qtbot.waitUntil(lambda: window.editor.toPlainText() == "ink ink ", timeout=3000)
    assert len(recognizer.samples) == 2
    assert all(len(sample.word.strokes) == 1 for sample in recognizer.samples)
    assert recognizer.samples[0].word is not recognizer.samples[1].word
