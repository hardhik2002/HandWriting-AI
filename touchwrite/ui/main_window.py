"""TouchWrite V2 live streaming whiteboard window."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from touchwrite.config.settings import Settings
from touchwrite.document.autosave import DocumentAutosave
from touchwrite.document.models import WhiteboardDocument, WordSlot
from touchwrite.ink.models import HandwrittenWord
from touchwrite.input.base import GestureAction
from touchwrite.input.gesture_engine import GestureEngine
from touchwrite.input.precision_touchpad_provider import (
    PrecisionTouchpadInputProvider,
    TouchpadApi,
)
from touchwrite.services.handwriting_service import CommitOutcome, HandwritingService
from touchwrite.services.recognition_stream import (
    RecognitionEvent,
    RecognitionFailure,
    RecognitionStream,
)
from touchwrite.ui.ink_canvas import InkCanvas


class _StreamSignals(QObject):
    preview_ready = Signal(object)
    commit_ready = Signal(object)
    failed = Signal(object)


@dataclass(slots=True)
class _PendingCommit:
    word: HandwrittenWord
    slot: WordSlot
    terminator: str


class MainWindow(QMainWindow):
    """Large layered whiteboard with non-blocking preview and commit recognition."""

    def __init__(self, settings: Settings, service: HandwritingService) -> None:
        super().__init__()
        self.settings = settings
        self.service = service
        self.autosave = DocumentAutosave(settings.autosave_path)
        restored = self.autosave.load() if settings.autosave_enabled else None
        self.document = restored or WhiteboardDocument()
        self._touchpad_provider: PrecisionTouchpadInputProvider | None = None
        self._last_outcome: CommitOutcome | None = None
        self._revision_id = 0
        self._next_commit_sequence = self._initial_sequence()
        self._pending_commits: dict[int, _PendingCommit] = {}
        self._commit_snapshots: dict[int, HandwrittenWord] = {}
        self._completed_events: dict[int, RecognitionEvent] = {}
        self._cleared_words: list[HandwrittenWord] = []
        self._recognition_pending = False
        self._preview_scheduled_at = 0.0

        self._stream_signals = _StreamSignals()
        self._stream_signals.preview_ready.connect(self._preview_ready)
        self._stream_signals.commit_ready.connect(self._commit_ready)
        self._stream_signals.failed.connect(self._recognition_failed)
        self.stream = RecognitionStream(
            service,
            on_preview=self._stream_signals.preview_ready.emit,
            on_commit=self._stream_signals.commit_ready.emit,
            on_failure=self._stream_signals.failed.emit,
        )

        self.setWindowTitle("TouchWrite V2 — Live Whiteboard")
        self.resize(1180, 820)
        self.setMinimumSize(820, 600)

        self.canvas = InkCanvas(settings)
        self.canvas.set_document(self.document)
        self.canvas.ink_changed.connect(self._ink_changed)
        self.canvas.stroke_started.connect(self._stroke_started)
        self.canvas.space_requested.connect(lambda: self._request_commit(" "))
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.editor = QTextEdit()
        self.editor.setVisible(False)
        self.editor.setReadOnly(True)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.canvas)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background: #f3f4f6; border: 0; }")

        self.prediction_label = QLabel("Prediction: —")
        self.confidence_label = QLabel("Model: TrOCR")
        self.mode_label = QLabel("Writing Mode ●")
        self.mode_label.setStyleSheet("color: #15803d; font-weight: 600;")
        self.state_label = QLabel("Ready")

        footer = QWidget()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(18, 8, 18, 8)
        footer_layout.addWidget(self.prediction_label)
        footer_layout.addStretch()
        footer_layout.addWidget(self.state_label)
        footer_layout.addSpacing(18)
        footer_layout.addWidget(self.confidence_label)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.scroll_area, 1)
        layout.addWidget(footer)
        layout.addWidget(self.editor)
        self.setCentralWidget(central)
        self._build_toolbar()
        self.setStyleSheet(
            "QMainWindow { background: #f3f4f6; }"
            "QToolBar { background: white; border: 0; border-bottom: 1px solid #e5e7eb; "
            "spacing: 6px; padding: 8px; }"
            "QToolButton { padding: 7px 10px; border-radius: 6px; }"
            "QToolButton:hover { background: #eff6ff; }"
            "QWidget#footer { background: white; border-top: 1px solid #e5e7eb; }"
        )

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(settings.preview_debounce_ms)
        self.preview_timer.timeout.connect(self._request_preview)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(settings.autosave_interval_ms)
        self.autosave_timer.timeout.connect(self._autosave)
        if settings.autosave_enabled:
            self.autosave_timer.start()

        self._sync_document_view()
        self.statusBar().showMessage(
            "Ready — write with one finger; two-finger tap/right-click commits"
        )
        self.canvas.setFocus()
        if settings.input_mode == "touchpad":
            self._start_writing_mode()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Whiteboard")
        toolbar.setMovable(False)
        toolbar.addWidget(QLabel("  TouchWrite  "))
        toolbar.addSeparator()
        toolbar.addWidget(self.mode_label)
        toolbar.addSeparator()
        actions = (
            ("Undo", self._undo),
            ("Redo", self._redo),
            ("Clear Current Ink", self._clear_ink),
            ("New Document", self._new_document),
            ("Save", self._save_document),
            ("Edit Text", self._edit_text),
            ("Export", self._export_text),
            ("Settings", self._show_settings),
            ("Diagnostics", self._show_diagnostics),
        )
        for label, callback in actions:
            action = QAction(label, self)
            action.triggered.connect(callback)
            toolbar.addAction(action)
        toolbar.addSeparator()
        self.mode_action = QAction("Toggle Writing Mode", self)
        self.mode_action.triggered.connect(self._toggle_writing_mode)
        toolbar.addAction(self.mode_action)
        self.addToolBar(toolbar)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        modifiers = event.modifiers()
        key = event.key()
        if modifiers & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_Z:
            self._undo()
            event.accept()
        elif modifiers & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_Y:
            self._redo()
            event.accept()
        elif key == Qt.Key.Key_Escape:
            self._clear_ink()
            event.accept()
        elif key == Qt.Key.Key_Backspace:
            self._backspace()
            event.accept()
        elif key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self._request_commit("\n")
            event.accept()
        elif key == Qt.Key.Key_Space:
            self._request_commit(" ")
            event.accept()
        else:
            super().keyPressEvent(event)

    def _stroke_started(self) -> None:
        self.preview_timer.stop()
        self.canvas.set_preview("")
        self._revision_id += 1
        self.stream.set_current_revision(self._revision_id)
        self.state_label.setText("Writing")

    def _ink_changed(self) -> None:
        self._revision_id += 1
        self.stream.set_current_revision(self._revision_id)
        self.stream.metrics.pointer_to_ink_latency_ms = self.canvas.pointer_to_ink_latency_ms
        if self.canvas.buffer.is_empty:
            self.preview_timer.stop()
            self.canvas.set_preview("")
            return
        self._preview_scheduled_at = time.perf_counter()
        self.preview_timer.start()
        self.state_label.setText("Writing")

    def _request_preview(self) -> None:
        if self.canvas.buffer.is_empty or self.canvas.buffer.active_stroke is not None:
            return
        self.state_label.setText("Recognizing…")
        self.stream.request_preview(
            self.canvas.snapshot(),
            self._revision_id,
            self.document.to_plain_text(),
            scheduled_at=self._preview_scheduled_at,
        )

    def _request_commit(self, terminator: str) -> None:
        self.preview_timer.stop()
        if self.canvas.buffer.is_empty:
            if self.document.insert_terminator(terminator):
                self._document_changed()
            return

        self.canvas.buffer.finalize_active()
        word = self.canvas.snapshot()
        sequence = self._next_commit_sequence
        self._next_commit_sequence += 1
        context = self.document.to_plain_text()
        slot = self.document.reserve_commit(sequence, terminator)
        self._pending_commits[sequence] = _PendingCommit(word, slot, terminator)
        self._commit_snapshots[sequence] = word
        self._recognition_pending = True
        self.canvas.clear_ink()
        self.stream.request_commit(
            word,
            self._revision_id,
            sequence,
            context=context,
            document_id=slot.document_id,
            line_index=slot.line_index,
            word_index=slot.word_index,
        )
        self._document_changed()
        self.state_label.setText("Recognizing…")

    def _preview_ready(self, value: object) -> None:
        if not isinstance(value, RecognitionEvent):
            return
        text = value.outcome.inserted_text
        self.canvas.set_preview(text)
        self.prediction_label.setText(f"Prediction: {text}")
        self.state_label.setText("Prediction ready")
        self._update_model_label(value.outcome)

    def _commit_ready(self, value: object) -> None:
        if not isinstance(value, RecognitionEvent):
            return
        sequence = value.request.commit_sequence_id
        if sequence is None:
            return
        self._pending_commits.pop(sequence, None)
        self._completed_events[sequence] = value
        outcome = value.outcome
        metadata = {
            "trajectory_hash": value.request.fingerprint,
            "inference_duration_ms": outcome.result.inference_duration_ms,
            "cache_reused": value.cache_reused,
            "model_name": outcome.result.model_name,
        }
        self.document.resolve_word(sequence, outcome.inserted_text, outcome.sample_id, metadata)
        self._last_outcome = outcome
        self._recognition_pending = bool(self._pending_commits)
        self.prediction_label.setText(f"Prediction: {outcome.inserted_text}")
        suffix = " (preview cache reused)" if value.cache_reused else ""
        self.state_label.setText("Committed")
        self.statusBar().showMessage(
            f"Committed in {outcome.result.inference_duration_ms:.0f} ms{suffix}"
        )
        self._update_model_label(outcome)
        self._document_changed()

    def _recognition_failed(self, value: object) -> None:
        if not isinstance(value, RecognitionFailure):
            return
        request = value.request
        if request.kind == "preview":
            self.state_label.setText("Writing")
            self.statusBar().showMessage(f"Preview unavailable: {value.message}")
            return
        sequence = request.commit_sequence_id
        pending = self._pending_commits.pop(sequence, None) if sequence is not None else None
        self._recognition_pending = bool(self._pending_commits)
        if sequence is not None:
            self.document.fail_word(sequence)
        if (
            pending is not None
            and self.canvas.buffer.is_empty
            and pending.slot.line_index == self.document.current_line_index
        ):
            self.document.remove_pending(pending.slot.commit_sequence_id)
            self.canvas.restore(pending.word)
        self.state_label.setText("Recognition failed")
        self.statusBar().showMessage(
            f"Recognition failed — ink preserved when safe: {value.message}"
        )
        self._document_changed()

    def _backspace(self) -> None:
        if not self.canvas.buffer.is_empty:
            self.canvas.undo_stroke()
            return
        if self.document.backspace():
            self._document_changed()

    def _undo(self) -> None:
        if not self.canvas.buffer.is_empty:
            self.canvas.undo_stroke()
            return
        if self._cleared_words:
            self.canvas.restore(self._cleared_words.pop())
            self.statusBar().showMessage("Cleared ink restored")
            return
        label = self.document.undo()
        if label is None:
            return
        if label.startswith("commit:"):
            sequence = int(label.partition(":")[2])
            word = self._commit_snapshots.get(sequence)
            if word is not None:
                self.canvas.restore(word)
        self._document_changed()
        self.statusBar().showMessage("Undid last whiteboard action")

    def _redo(self) -> None:
        label = self.document.redo()
        if label is not None:
            if label.startswith("commit:"):
                sequence = int(label.partition(":")[2])
                event = self._completed_events.get(sequence)
                if event is not None:
                    outcome = event.outcome
                    self.document.resolve_word(
                        sequence,
                        outcome.inserted_text,
                        outcome.sample_id,
                        {
                            "trajectory_hash": event.request.fingerprint,
                            "inference_duration_ms": outcome.result.inference_duration_ms,
                            "cache_reused": event.cache_reused,
                            "model_name": outcome.result.model_name,
                        },
                    )
            self.canvas.clear_ink()
            self._document_changed()
            self.statusBar().showMessage("Redid whiteboard action")

    def _clear_ink(self) -> None:
        if not self.canvas.buffer.is_empty:
            self._cleared_words.append(self.canvas.snapshot())
            self.canvas.clear_ink()
            self.statusBar().showMessage("Current ink cleared")

    def _new_document(self) -> None:
        self.document.new_document()
        self.canvas.clear_ink()
        self.canvas.set_preview("")
        self._document_changed()
        self.statusBar().showMessage("New document created")

    def _save_document(self) -> None:
        self._autosave()
        self.statusBar().showMessage(f"Saved to {self.settings.autosave_path}")

    def _autosave(self) -> None:
        if self.settings.autosave_enabled:
            self.autosave.save(self.document)

    def _export_text(self) -> None:
        filename, _selected = QFileDialog.getSaveFileName(
            self, "Export plain text", "touchwrite.txt", "Text files (*.txt)"
        )
        if not filename:
            return
        Path(filename).write_text(self.document.to_plain_text(), encoding="utf-8")
        self.statusBar().showMessage(f"Exported {filename}")

    def _edit_text(self) -> None:
        text, accepted = QInputDialog.getMultiLineText(
            self,
            "Edit document text",
            "Plain text:",
            self.document.to_plain_text(),
        )
        if accepted:
            self.document.replace_plain_text(text)
            self._document_changed()
            self.statusBar().showMessage("Document text updated")

    def _show_settings(self) -> None:
        QMessageBox.information(
            self,
            "TouchWrite settings",
            f"Preview debounce: {self.settings.preview_debounce_ms} ms\n"
            f"Model: {self.settings.model_name}\n"
            f"Beams: {self.settings.beam_width}\n"
            f"Processor use_fast: {self.settings.processor_use_fast}",
        )

    def _show_diagnostics(self) -> None:
        metrics = self.stream.snapshot_metrics()
        lines = [
            f"{name.replace('_', ' ').title()}: {value}"
            for name, value in metrics.to_dict().items()
        ]
        QMessageBox.information(self, "Streaming diagnostics", "\n".join(lines))

    def _document_changed(self) -> None:
        self._sync_document_view()
        self._autosave()
        QTimer.singleShot(0, self._keep_active_line_visible)

    def _sync_document_view(self) -> None:
        self.canvas.set_document(self.document)
        self.editor.setPlainText(self.document.to_plain_text())

    def _keep_active_line_visible(self) -> None:
        x, y = self.canvas.cursor_position()
        self.scroll_area.ensureVisible(int(x), int(y), 80, 100)

    def _initial_sequence(self) -> int:
        return max(
            0,
            max(
                (
                    word.commit_sequence_id
                    for line in self.document.lines
                    for word in line.words
                ),
                default=0,
            ),
        ) + 1

    def _update_model_label(self, outcome: CommitOutcome) -> None:
        self.confidence_label.setText(
            f"Model: TrOCR · {outcome.result.inference_duration_ms:.0f} ms"
        )

    def _toggle_writing_mode(self) -> None:
        if self._touchpad_provider is None:
            self._start_writing_mode()
        else:
            self._stop_writing_mode()

    def _start_writing_mode(self) -> None:
        if self._touchpad_provider is not None:
            return
        if not TouchpadApi.is_available():
            self.statusBar().showMessage(
                "Native touchpad APIs unavailable; mouse fallback remains active"
            )
            return
        engine = GestureEngine(
            self.settings.two_finger_tap_max_ms,
            self.settings.two_finger_max_travel,
            self.settings.two_finger_overlap_min_ms,
        )
        application = QCoreApplication.instance()
        if application is None:
            return
        provider: PrecisionTouchpadInputProvider | None = None
        try:
            provider = PrecisionTouchpadInputProvider(engine, self._native_gesture)
            application.installNativeEventFilter(provider)
            provider.start(int(self.canvas.winId()))
        except OSError as error:
            if provider is not None:
                application.removeNativeEventFilter(provider)
            self.statusBar().showMessage(f"Could not start native touchpad input: {error}")
            return
        self._touchpad_provider = provider
        self.mode_label.setText("Writing Mode ●")
        self.statusBar().showMessage("Writing mode active — two-finger tap commits")

    def _stop_writing_mode(self) -> None:
        provider, self._touchpad_provider = self._touchpad_provider, None
        if provider is not None:
            provider.stop()
            application = QCoreApplication.instance()
            if application is not None:
                application.removeNativeEventFilter(provider)
        self.mode_label.setText("Mouse Mode ●")

    def _native_gesture(self, action: GestureAction) -> None:
        if action is GestureAction.SPACE:
            self._request_commit(" ")

    def closeEvent(self, event: object) -> None:  # noqa: N802
        self._autosave()
        self.preview_timer.stop()
        self.autosave_timer.stop()
        self.stream.shutdown(wait=False)
        self._stop_writing_mode()
        super().closeEvent(event)

    def _correct_last_prediction(self) -> None:
        outcome = self._last_outcome
        if outcome is None or outcome.sample_id is None or self.service.store is None:
            self.statusBar().showMessage("No persisted prediction is available to correct")
            return
        corrected, accepted = QInputDialog.getText(
            self,
            "Correct prediction",
            "Expected text:",
            text=outcome.word.predicted_text or "",
        )
        corrected = corrected.strip()
        if accepted and corrected:
            self.service.store.update_correction(outcome.sample_id, corrected)
            self.statusBar().showMessage(f"Saved correction for sample {outcome.sample_id}")
