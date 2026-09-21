"""Real-time mouse-backed digital ink canvas."""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from touchwrite.config.settings import Settings


class InkCanvas(QWidget):
    """Capture and render mouse strokes without blocking the UI thread."""

    ink_changed = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._strokes: list[list[tuple[QPointF, int]]] = []
        self._active: list[tuple[QPointF, int]] | None = None
        self.setMinimumHeight(260)
        self.setMouseTracking(True)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor("white"))
        self.setPalette(palette)

    @property
    def strokes(self) -> tuple[tuple[tuple[QPointF, int], ...], ...]:
        return tuple(tuple(stroke) for stroke in self._strokes)

    def clear_ink(self) -> None:
        self._strokes.clear()
        self._active = None
        self.update()
        self.ink_changed.emit()

    def undo_stroke(self) -> None:
        if self._active is not None:
            self._active = None
        elif self._strokes:
            self._strokes.pop()
        self.update()
        self.ink_changed.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._active = [(event.position(), time.monotonic_ns())]
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._active is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._active.append((event.position(), time.monotonic_ns()))
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._active is not None:
            self._active.append((event.position(), time.monotonic_ns()))
            self._strokes.append(self._active)
            self._active = None
            self.update()
            self.ink_changed.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: object) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("white"))
        painter.setPen(
            QPen(
                QColor("#111827"),
                self.settings.stroke_width,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        for stroke in [*self._strokes, *([self._active] if self._active else [])]:
            if not stroke:
                continue
            if len(stroke) == 1:
                painter.drawPoint(stroke[0][0])
                continue
            path = QPainterPath(stroke[0][0])
            for point, _timestamp in stroke[1:]:
                path.lineTo(point)
            painter.drawPath(path)

