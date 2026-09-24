"""TouchWrite V2 live streaming whiteboard window."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QInputDevice, QKeyEvent, QPointingDevice
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QTextEdit,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from touchwrite.config.settings import Settings
from touchwrite.diagnostics.timeline import RecognitionTimeline
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
from touchwrite.ui.touch_alignment import TouchAlignmentDialog


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
        self._pending_commit_terminator: str | None = None
        self._active_input_mode = self._resolve_input_mode(
            settings.input_mode, settings.auto_detect_input
        )

        self._stream_signals = _StreamSignals()
        self._stream_signals.preview_ready.connect(self._preview_ready)
        self._stream_signals.commit_ready.connect(self._commit_ready)
        self._stream_signals.failed.connect(self._recognition_failed)
        timeline_path = (
            settings.touchscreen_debug_dir / "recognition_timeline.jsonl"
            if settings.debug_input or settings.debug_recognition
            else None
        )
        self.recognition_timeline = RecognitionTimeline(timeline_path)
        self.stream = RecognitionStream(
            service,
            on_preview=self._stream_signals.preview_ready.emit,
            on_commit=self._stream_signals.commit_ready.emit,
            on_failure=self._stream_signals.failed.emit,
            on_trace=self.recognition_timeline.record,
        )

        self.setWindowTitle("TouchWrite V2 — Live Whiteboard")
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        width = min(1180, available.width() - 32) if available is not None else 1180
        height = min(760, available.height() - 32) if available is not None else 760
        self.resize(max(760, width), max(560, height))
        self.setMinimumSize(760, 560)

        self.canvas = InkCanvas(settings)
        self.canvas.set_input_mode(self._active_input_mode)
        self.canvas.set_document(self.document)
        self.canvas.ink_changed.connect(self._ink_changed)
        self.canvas.stroke_started.connect(self._stroke_started)
        self.canvas.stroke_ended.connect(self._stroke_ended)
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
        self.mode_label = QLabel()
        self.mode_label.setObjectName("modeLabel")
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
        self._build_toolbars()
        self.setStyleSheet(
            "QMainWindow { background: #f3f4f6; }"
            "QToolBar { background: #ffffff; border: 0; border-bottom: 1px solid #cbd5e1; "
            "spacing: 7px; padding: 5px 10px; color: #0f172a; }"
            "QToolButton { color: #0f172a; background: #ffffff; border: 1px solid #cbd5e1; "
            "min-height: 42px; padding: 0 8px; border-radius: 8px; font-weight: 600; }"
            "QToolButton:hover { background: #eff6ff; border-color: #60a5fa; }"
            "QToolButton:pressed { background: #dbeafe; }"
            "QToolButton:disabled { color: #94a3b8; background: #f8fafc; }"
            "QToolButton#primaryAction { color: white; background: #2563eb; "
            "border-color: #1d4ed8; }"
            "QToolButton#primaryAction:pressed { background: #1d4ed8; }"
            "QComboBox { color: #0f172a; background: white; border: 1px solid #94a3b8; "
            "min-height: 42px; min-width: 155px; padding: 0 10px; border-radius: 8px; }"
            "QMenu { color: #0f172a; background: white; border: 1px solid #94a3b8; }"
            "QMenu::item { min-height: 40px; padding: 2px 18px; }"
            "QMenu::item:selected { background: #dbeafe; }"
            "QToolBar QLabel { color: #0f172a; }"
            "QLabel#brandLabel { color: #0f172a; font-size: 20px; font-weight: 700; }"
            "QLabel#modeLabel { color: #15803d; font-size: 14px; font-weight: 700; }"
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
        self._update_mode_label()
        if self._active_input_mode == "touchpad":
            self._start_writing_mode()
        self._update_toolbar_responsiveness(self.width())

    def _build_toolbars(self) -> None:
        identity = QToolBar("Identity")
        identity.setObjectName("identityToolbar")
        identity.setMovable(False)
        identity.setFloatable(False)
        identity.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        brand = QLabel("TouchWrite")
        brand.setObjectName("brandLabel")
        identity.addWidget(brand)
        identity.addSeparator()
        identity.addWidget(self.mode_label)
        identity.addSeparator()
        identity.addWidget(QLabel("Input:"))
        self.input_mode_combo = QComboBox()
        self.input_mode_combo.addItem("Touch Screen", "touchscreen")
        self.input_mode_combo.addItem("Precision Touchpad", "touchpad")
        self.input_mode_combo.addItem("Mouse", "mouse")
        index = self.input_mode_combo.findData(self._active_input_mode)
        self.input_mode_combo.setCurrentIndex(max(0, index))
        self.input_mode_combo.currentIndexChanged.connect(self._input_mode_changed)
        identity.addWidget(self.input_mode_combo)
        identity.addSeparator()
        self._identity_optional_actions: list[QAction] = []
        for label, callback in (
            ("New Document", self._new_document),
            ("Edit Text", self._edit_text),
        ):
            action = QAction(label, self)
            action.triggered.connect(callback)
            identity.addAction(action)
            self._identity_optional_actions.append(action)
        self.addToolBar(identity)

        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        toolbar = QToolBar("Actions")
        toolbar.setObjectName("actionsToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        actions = (
            ("Undo", self._undo),
            ("Redo", self._redo),
            ("Clear Ink", self._clear_ink),
            ("Commit / Space", lambda: self._request_commit(" ")),
            ("New Line", lambda: self._request_commit("\n")),
            ("Save", self._save_document),
            ("Export", self._export_text),
            ("Settings", self._show_settings),
            ("Diagnostics", self._show_diagnostics),
        )
        self._secondary_toolbar_actions: list[QAction] = []
        secondary_labels = {"Save", "Export", "Settings", "Diagnostics"}
        for label, callback in actions:
            action = QAction(label, self)
            action.setObjectName(label.lower().replace(" ", "_").replace("/", "_"))
            action.triggered.connect(callback)
            toolbar.addAction(action)
            if label in secondary_labels:
                self._secondary_toolbar_actions.append(action)
        self.more_menu = QMenu(self)
        overflow_callbacks = {
            "Save": self._save_document,
            "Export": self._export_text,
            "Settings": self._show_settings,
            "Diagnostics": self._show_diagnostics,
            "New Document": self._new_document,
            "Edit Text": self._edit_text,
        }
        for label, callback in overflow_callbacks.items():
            menu_action = self.more_menu.addAction(label)
            menu_action.triggered.connect(callback)
        self.more_button = QToolButton()
        self.more_button.setText("More")
        self.more_button.setMenu(self.more_menu)
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar.addWidget(self.more_button)
        self.addToolBar(toolbar)
        for label in {"Commit / Space", "New Line"}:
            action = next(item for item in toolbar.actions() if item.text() == label)
            button = toolbar.widgetForAction(action)
            if button is not None:
                button.setObjectName("primaryAction")

    def resizeEvent(self, event: object) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_toolbar_responsiveness(self.width())

    def _update_toolbar_responsiveness(self, width: int) -> None:
        wide = width >= 1050
        for action in getattr(self, "_secondary_toolbar_actions", []):
            action.setVisible(wide)
        for action in getattr(self, "_identity_optional_actions", []):
            action.setVisible(wide)
        if hasattr(self, "more_button"):
            self.more_button.setVisible(not wide)

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
        existing_strokes = len(self.canvas.strokes)
        self.recognition_timeline.record(
            "stroke_started",
            revision_id=self._revision_id + 1,
            stroke_count=existing_strokes + 1,
        )
        if existing_strokes:
            self.recognition_timeline.record(
                "new_stroke_started",
                revision_id=self._revision_id + 1,
                stroke_count=existing_strokes + 1,
            )
        self.preview_timer.stop()
        self.canvas.set_preview("")
        self._revision_id += 1
        self.stream.set_current_revision(self._revision_id)
        self.state_label.setText("Writing")

    def _stroke_ended(self) -> None:
        self.recognition_timeline.record(
            "stroke_ended",
            revision_id=self._revision_id,
            stroke_count=len(self.canvas.strokes),
        )
        if self._pending_commit_terminator is None:
            return
        terminator = self._pending_commit_terminator
        self._pending_commit_terminator = None
        QTimer.singleShot(0, lambda: self._commit_complete_snapshot(terminator))

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
        self.recognition_timeline.record(
            "preview_scheduled",
            revision_id=self._revision_id,
            debounce_ms=self.settings.preview_debounce_ms,
        )
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
        self.recognition_timeline.record(
            "commit_pressed",
            revision_id=self._revision_id,
            terminator=terminator,
            active_input=self.canvas.input_active,
        )
        self.preview_timer.stop()
        if self.canvas.input_active:
            self._pending_commit_terminator = terminator
            self.state_label.setText("Finishing stroke…")
            return
        self._commit_complete_snapshot(terminator)

    def _commit_complete_snapshot(self, terminator: str) -> None:
        self.preview_timer.stop()
        if self.canvas.buffer.is_empty:
            if self.document.insert_terminator(terminator):
                self._document_changed()
            return

        word = self.canvas.snapshot()
        snapshot_revision = self._revision_id
        self._revision_id += 1
        self.stream.cancel_pending_preview(self._revision_id)
        screen = self.canvas.screen()
        word.recognition_metadata.update(
            {
                "input_mode": self._active_input_mode,
                "capture_coordinate_space": "canvas-local Qt logical pixels",
                "display_coordinate_space": "whiteboard document logical pixels",
                "recognition_coordinate_space": "undistorted canvas-local Qt logical pixels",
                "canvas_size": [self.canvas.width(), self.canvas.height()],
                "widget_device_pixel_ratio": self.canvas.devicePixelRatioF(),
                "screen_device_pixel_ratio": (
                    screen.devicePixelRatio() if screen is not None else 1.0
                ),
                "scroll_offset": [
                    self.scroll_area.horizontalScrollBar().value(),
                    self.scroll_area.verticalScrollBar().value(),
                ],
            }
        )
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
            snapshot_revision,
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
        screen = self.canvas.screen()
        QMessageBox.information(
            self,
            "TouchWrite settings",
            f"Preview debounce: {self.settings.preview_debounce_ms} ms\n"
            f"Model: {self.settings.model_name}\n"
            f"Beams: {self.settings.beam_width}\n"
            f"Processor use_fast: {self.settings.processor_use_fast}\n"
            f"Input mode: {self._mode_display_name(self._active_input_mode)}\n"
            f"Widget DPR: {self.canvas.devicePixelRatioF():.2f}\n"
            f"Screen DPR: {screen.devicePixelRatio() if screen is not None else 1.0:.2f}",
        )

    def _show_diagnostics(self) -> None:
        dialog = TouchAlignmentDialog(
            self.settings.touchscreen_debug_dir / "touch_alignment_latest.json",
            self,
        )
        dialog.exec()
        touch_metrics = dialog.canvas.metrics()
        stream_metrics = self.stream.snapshot_metrics()
        self.statusBar().showMessage(
            f"Alignment samples: {touch_metrics['samples']} · "
            f"cache reuses: {stream_metrics.cache_reuse_count} · "
            f"stale previews: {stream_metrics.stale_preview_discard_count}"
        )

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

    @staticmethod
    def _resolve_input_mode(configured: str, auto_detect: bool = True) -> str:
        if configured not in {"auto", "mouse"} or not auto_detect:
            return configured
        if any(
            device.type() == QPointingDevice.DeviceType.TouchScreen
            for device in QInputDevice.devices()
        ):
            return "touchscreen"
        return "mouse"

    @staticmethod
    def _mode_display_name(mode: str) -> str:
        return {
            "touchscreen": "Touch Screen",
            "touchpad": "Precision Touchpad",
            "mouse": "Mouse",
        }.get(mode, mode.title())

    def _input_mode_changed(self, index: int) -> None:
        mode = str(self.input_mode_combo.itemData(index))
        if mode == self._active_input_mode:
            return
        self._stop_writing_mode()
        self._active_input_mode = mode
        self.canvas.set_input_mode(mode)
        if mode == "touchpad":
            self._start_writing_mode()
        self._update_mode_label()
        self.canvas.setFocus()

    def _update_mode_label(self) -> None:
        self.mode_label.setText(f"● {self._mode_display_name(self._active_input_mode)}")

    def _toggle_writing_mode(self) -> None:
        next_mode = "mouse" if self._active_input_mode == "touchpad" else "touchpad"
        self.input_mode_combo.setCurrentIndex(self.input_mode_combo.findData(next_mode))

    def _start_writing_mode(self) -> None:
        if self._touchpad_provider is not None:
            return
        if not TouchpadApi.is_available():
            self.statusBar().showMessage(
                "Native touchpad APIs unavailable; mouse fallback remains active"
            )
            self._active_input_mode = "mouse"
            self.canvas.set_input_mode("mouse")
            self.input_mode_combo.blockSignals(True)
            self.input_mode_combo.setCurrentIndex(self.input_mode_combo.findData("mouse"))
            self.input_mode_combo.blockSignals(False)
            self._update_mode_label()
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
        self._update_mode_label()
        self.statusBar().showMessage("Precision Touchpad active — two-finger tap commits")

    def _stop_writing_mode(self) -> None:
        provider, self._touchpad_provider = self._touchpad_provider, None
        if provider is not None:
            provider.stop()
            application = QCoreApplication.instance()
            if application is not None:
                application.removeNativeEventFilter(provider)
        self._update_mode_label()

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
