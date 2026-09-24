"""Standalone touchscreen collection window; the production whiteboard remains untouched."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from touchwrite.collection.accuracy import (
    load_accuracy_session,
    next_accuracy_prompt,
    record_accuracy_sample,
    write_baseline_reports,
)
from touchwrite.config.settings import Settings
from touchwrite.ink.models import HandwrittenWord
from touchwrite.services.handwriting_service import CommitOutcome, HandwritingService
from touchwrite.ui.ink_canvas import InkCanvas
from touchwrite.ui.recognition_worker import RecognitionWorker


class AccuracyCollectorWindow(QMainWindow):
    """Display authoritative labels and collect one independently committed word at a time."""

    def __init__(
        self,
        settings: Settings,
        service: HandwritingService,
        session_dir: Path,
        *,
        baseline_json: Path = Path("reports/touchscreen_baseline.json"),
        baseline_markdown: Path = Path("reports/touchscreen_baseline.md"),
    ) -> None:
        super().__init__()
        self.settings = settings
        self.service = service
        self.session_dir = session_dir
        self.baseline_json = baseline_json
        self.baseline_markdown = baseline_markdown
        self.manifest = load_accuracy_session(session_dir)
        self.current_prompt = next_accuracy_prompt(self.manifest)
        self._worker: RecognitionWorker | None = None
        self._submitted_word: HandwrittenWord | None = None
        self.setWindowTitle("TouchWrite Touchscreen Accuracy Collection")
        self.resize(1180, 780)
        self.setMinimumSize(800, 620)

        self.progress_label = QLabel()
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.target_label = QLabel()
        self.target_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        target_font = QFont("Segoe UI", 34)
        target_font.setBold(True)
        self.target_label.setFont(target_font)
        self.instruction_label = QLabel(
            "Write the displayed target naturally. Do not imitate the prediction. "
            "Submit only when the word is complete."
        )
        self.instruction_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.canvas = InkCanvas(settings)
        self.canvas.set_input_mode("touchscreen")
        self.canvas.ink_changed.connect(self._update_actions)

        self.undo_button = QPushButton("Undo stroke")
        self.clear_button = QPushButton("Clear / retry")
        self.submit_button = QPushButton("Submit sample")
        self.undo_button.clicked.connect(self.canvas.undo_stroke)
        self.clear_button.clicked.connect(self._clear)
        self.submit_button.clicked.connect(self._submit)
        self.submit_button.setDefault(True)

        controls = QHBoxLayout()
        controls.addStretch()
        controls.addWidget(self.undo_button)
        controls.addWidget(self.clear_button)
        controls.addWidget(self.submit_button)
        controls.addStretch()
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.target_label)
        layout.addWidget(self.instruction_label)
        layout.addWidget(self.canvas, 1)
        layout.addLayout(controls)
        layout.addWidget(self.status_label)
        self.setCentralWidget(central)
        self.setStyleSheet(
            "QMainWindow { background: #f1f5f9; }"
            "QLabel { color: #0f172a; }"
            "QPushButton { min-height: 44px; padding: 0 18px; font-weight: 600; }"
            "QPushButton:default { color: white; background: #2563eb; border-radius: 8px; }"
        )
        self._show_prompt()
        self._update_actions()

    def _show_prompt(self) -> None:
        self.manifest = load_accuracy_session(self.session_dir)
        self.current_prompt = next_accuracy_prompt(self.manifest)
        completed = len(self.manifest["samples"])
        total = len(self.manifest["prompts"])
        self.progress_label.setText(
            f"Session {self.manifest['session_id']} — sample {min(completed + 1, total)} of {total}"
        )
        if self.current_prompt is None:
            self.target_label.setText("Collection complete")
            self.instruction_label.setText(
                f"Baseline written to {self.baseline_markdown} and {self.baseline_json}."
            )
            self.status_label.setText("All displayed-label samples are saved.")
        else:
            self.target_label.setText(str(self.current_prompt["expected"]))
            self.instruction_label.setText(
                "Write exactly the displayed target once, naturally, then tap Submit sample."
            )

    def _submit(self) -> None:
        if self.current_prompt is None or self._worker is not None or self.canvas.input_active:
            return
        if not self.canvas.strokes:
            self.status_label.setText("Write the target before submitting.")
            return
        word = self.canvas.snapshot()
        word.expected_text = str(self.current_prompt["expected"])
        screen = self.canvas.screen()
        word.recognition_metadata.update(
            {
                "input_mode": "touchscreen",
                "collection_session_id": self.manifest["session_id"],
                "collection_prompt_id": self.current_prompt["prompt_id"],
                "displayed_ground_truth": word.expected_text,
                "canvas_size": [self.canvas.width(), self.canvas.height()],
                "widget_device_pixel_ratio": self.canvas.devicePixelRatioF(),
                "physical_dpi_x": screen.physicalDotsPerInchX() if screen else None,
                "physical_dpi_y": screen.physicalDotsPerInchY() if screen else None,
            }
        )
        self._submitted_word = word
        self._worker = RecognitionWorker(self.service, word, "", "")
        self._worker.signals.succeeded.connect(self._recognition_succeeded)
        self._worker.signals.failed.connect(self._recognition_failed)
        self.status_label.setText("Recognizing and preserving exact artifacts…")
        self._set_busy(True)
        QThreadPool.globalInstance().start(self._worker)

    def _recognition_succeeded(self, outcome: CommitOutcome) -> None:
        try:
            if self.current_prompt is None or self._submitted_word is None:
                raise RuntimeError("collection prompt changed during recognition")
            raw_image, processed_image = self.service.render_for_recognition(outcome.word)
            record_accuracy_sample(
                self.session_dir,
                self.current_prompt["prompt_id"],
                outcome.word,
                raw_image,
                processed_image,
                outcome.result,
            )
            report = write_baseline_reports(
                self.session_dir, self.baseline_json, self.baseline_markdown
            )
            self.canvas.clear_ink()
            self.status_label.setText(
                f"Saved: {outcome.word.expected_text!r} → {outcome.result.text!r}; "
                f"running exact accuracy {report['exact_accuracy']:.1%}"
            )
            self._worker = None
            self._submitted_word = None
            self._show_prompt()
            self._set_busy(False)
        except Exception as error:
            self._recognition_failed(str(error))

    def _recognition_failed(self, message: str) -> None:
        self._worker = None
        self._submitted_word = None
        self._set_busy(False)
        self.status_label.setText(f"Not saved: {message}")
        QMessageBox.warning(self, "Sample not saved", message)

    def _clear(self) -> None:
        if self._worker is None:
            self.canvas.clear_ink()
            self.status_label.setText("Cleared. Write the same displayed target again.")

    def _set_busy(self, busy: bool) -> None:
        self.canvas.setEnabled(not busy)
        self.undo_button.setEnabled(not busy)
        self.clear_button.setEnabled(not busy)
        self.submit_button.setEnabled(not busy and bool(self.canvas.strokes))

    def _update_actions(self) -> None:
        busy = self._worker is not None
        has_ink = bool(self.canvas.strokes)
        self.undo_button.setEnabled(not busy and has_ink)
        self.clear_button.setEnabled(not busy and has_ink)
        self.submit_button.setEnabled(
            not busy and has_ink and self.current_prompt is not None
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self._submit()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self._clear()
            event.accept()
        elif (
            event.key() == Qt.Key.Key_Z
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.canvas.undo_stroke()
            event.accept()
        else:
            super().keyPressEvent(event)
