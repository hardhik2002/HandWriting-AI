"""Real-time mouse-backed digital ink canvas."""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from touchwrite.config.settings import Settings
from touchwrite.ink.models import HandwrittenWord, Point, Stroke
from touchwrite.ink.stroke_buffer import StrokeBuffer


class InkCanvas(QWidget):
    """Capture and render mouse strokes without blocking the UI thread."""

    ink_changed = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.buffer = StrokeBuffer(settings.min_stroke_points)
        self.setMinimumHeight(260)
        self.setMouseTracking(True)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor("white"))
        self.setPalette(palette)

    @property
    def strokes(self) -> tuple[Stroke, ...]:
        return self.buffer.strokes

    def snapshot(self) -> HandwrittenWord:
        return self.buffer.snapshot()

    def restore(self, word: HandwrittenWord) -> None:
        self.buffer.restore(word)
        self.update()
        self.ink_changed.emit()

    def clear_ink(self) -> None:
        self.buffer.clear()
        self.update()
        self.ink_changed.emit()

    def undo_stroke(self) -> None:
        self.buffer.undo()
        self.update()
        self.ink_changed.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.buffer.begin(self._to_point(event.position()))
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.buffer.active_stroke is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.buffer.add(self._to_point(event.position()))
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.buffer.active_stroke is not None:
            self.buffer.end(self._to_point(event.position()))
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
        strokes = list(self.buffer.strokes)
        if self.buffer.active_stroke is not None:
            strokes.append(self.buffer.active_stroke)
        for stroke in strokes:
            if not stroke.points:
                continue
            positions = [
                QPointF(point.x * self.width(), point.y * self.height())
                for point in stroke.points
            ]
            if len(positions) == 1:
                painter.drawPoint(positions[0])
                continue
            path = QPainterPath(positions[0])
            for position in positions[1:]:
                path.lineTo(position)
            painter.drawPath(path)

    def _to_point(self, position: QPointF) -> Point:
        width = max(1, self.width())
        height = max(1, self.height())
        return Point(
            x=min(1.0, max(0.0, position.x() / width)),
            y=min(1.0, max(0.0, position.y() / height)),
            x_raw=position.x(),
            y_raw=position.y(),
            timestamp_ns=time.monotonic_ns(),
            contact_id=0,
        )
