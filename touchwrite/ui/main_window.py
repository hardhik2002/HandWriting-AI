"""Main TouchWrite application window."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from touchwrite.config.settings import Settings
from touchwrite.ink.models import HandwrittenWord
from touchwrite.services.handwriting_service import CommitOutcome, HandwritingService
from touchwrite.ui.ink_canvas import InkCanvas
from touchwrite.ui.recognition_worker import RecognitionWorker


@dataclass(slots=True)
class _CommitAction:
    text_before: str
    word: HandwrittenWord


class MainWindow(QMainWindow):
    """Primary UI; recognition services are attached in later phases."""

    def __init__(self, settings: Settings, service: HandwritingService) -> None:
        super().__init__()
        self.settings = settings
        self.service = service
        self._recognition_pending = False
        self._history: list[_CommitAction] = []
        self._pending_action: _CommitAction | None = None
        self.setWindowTitle("TouchWrite")
        self.resize(1000, 720)

        self.canvas = InkCanvas(settings)
        self.editor = QTextEdit()
        self.editor.setPlaceholderText("Recognized text appears here and remains editable.")
        self.prediction_label = QLabel("Prediction: —")
        self.confidence_label = QLabel("Confidence: —")
        self.mode_label = QLabel(f"Input mode: {settings.input_mode}")

        clear_button = QPushButton("Clear ink")
        clear_button.clicked.connect(self.canvas.clear_ink)
        undo_button = QPushButton("Undo stroke")
        undo_button.clicked.connect(self._undo)
        commit_button = QPushButton("Recognize + Space")
        commit_button.clicked.connect(lambda: self._request_commit(" "))

        controls = QHBoxLayout()
        controls.addWidget(clear_button)
        controls.addWidget(undo_button)
        controls.addWidget(commit_button)
        controls.addStretch()
        controls.addWidget(self.mode_label)

        ink_panel = QWidget()
        ink_layout = QVBoxLayout(ink_panel)
        ink_layout.addWidget(QLabel("Digital Ink Canvas"))
        ink_layout.addWidget(self.canvas, 1)
        ink_layout.addWidget(self.prediction_label)
        ink_layout.addWidget(self.confidence_label)
        ink_layout.addLayout(controls)

        text_panel = QWidget()
        text_layout = QVBoxLayout(text_panel)
        text_layout.addWidget(QLabel("Recognized Text"))
        text_layout.addWidget(self.editor)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(ink_panel)
        splitter.addWidget(text_panel)
        splitter.setSizes([440, 240])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Ready — mouse fallback mode")
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.canvas.setFocus()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self.editor.hasFocus():
            super().keyPressEvent(event)
            return
        modifiers = event.modifiers()
        key = event.key()
        if modifiers & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_Z:
            self._undo()
            event.accept()
        elif key == Qt.Key.Key_Escape:
            self.canvas.clear_ink()
            event.accept()
        elif key == Qt.Key.Key_Backspace:
            self._backspace()
            event.accept()
        elif key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self._request_commit("\n")
            event.accept()
        elif key == Qt.Key.Key_Space and self.settings.input_mode == "mouse":
            self._request_commit(" ")
            event.accept()
        else:
            super().keyPressEvent(event)

    def _request_commit(self, terminator: str) -> None:
        if self._recognition_pending:
            self.statusBar().showMessage("Recognition is already running")
            return
        if self.canvas.buffer.is_empty:
            self._insert_text(terminator)
            return
        self.canvas.buffer.finalize_active()
        word = self.canvas.snapshot()
        self._pending_action = _CommitAction(self.editor.toPlainText(), word)
        self._recognition_pending = True
        self.canvas.setEnabled(False)
        self.statusBar().showMessage("Recognizing…")
        worker = RecognitionWorker(self.service, word, terminator, self.editor.toPlainText())
        worker.signals.succeeded.connect(self._recognition_succeeded)
        worker.signals.failed.connect(self._recognition_failed)
        self._thread_pool().start(worker)

    @staticmethod
    def _thread_pool():
        from PySide6.QtCore import QThreadPool

        return QThreadPool.globalInstance()

    def _recognition_succeeded(self, value: object) -> None:
        outcome = value
        if not isinstance(outcome, CommitOutcome):
            self._recognition_failed("invalid recognition result")
            return
        self._insert_text(outcome.inserted_text)
        self.prediction_label.setText(f"Prediction: {outcome.result.text}")
        confidence = (
            f"{outcome.result.confidence:.3f}"
            if outcome.result.confidence is not None
            else "not reported"
        )
        self.confidence_label.setText(f"Confidence: {confidence}")
        if self._pending_action is not None:
            self._history.append(self._pending_action)
        self._pending_action = None
        self.canvas.clear_ink()
        self._recognition_pending = False
        self.canvas.setEnabled(True)
        self.canvas.setFocus()
        self.statusBar().showMessage(
            f"Recognized in {outcome.result.inference_duration_ms:.0f} ms"
        )

    def _recognition_failed(self, message: str) -> None:
        self._recognition_pending = False
        self._pending_action = None
        self.canvas.setEnabled(True)
        self.canvas.setFocus()
        self.statusBar().showMessage(f"Recognition failed — ink preserved: {message}")

    def _insert_text(self, text: str) -> None:
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)

    def _backspace(self) -> None:
        if not self.canvas.buffer.is_empty:
            self.canvas.undo_stroke()
            return
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.deletePreviousChar()
        self.editor.setTextCursor(cursor)

    def _undo(self) -> None:
        if not self.canvas.buffer.is_empty:
            self.canvas.undo_stroke()
            return
        if self._history:
            action = self._history.pop()
            self.editor.setPlainText(action.text_before)
            self.canvas.restore(action.word)
            self.statusBar().showMessage("Committed word restored to canvas")
            return
        self.editor.undo()
