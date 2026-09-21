"""Main TouchWrite application window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
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
from touchwrite.ui.ink_canvas import InkCanvas


class MainWindow(QMainWindow):
    """Primary UI; recognition services are attached in later phases."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
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
        undo_button.clicked.connect(self.canvas.undo_stroke)

        controls = QHBoxLayout()
        controls.addWidget(clear_button)
        controls.addWidget(undo_button)
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

        clear_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        clear_shortcut.activated.connect(self.canvas.clear_ink)

