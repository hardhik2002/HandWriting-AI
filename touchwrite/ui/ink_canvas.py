"""Real-time mouse-backed digital ink canvas."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from touchwrite.config.settings import Settings
from touchwrite.ink.models import HandwrittenWord, Point, Stroke
from touchwrite.ink.stroke_buffer import StrokeBuffer
from touchwrite.input.mouse_provider import MouseInputProvider


class InkCanvas(QWidget):
    """Capture and render mouse strokes without blocking the UI thread."""

    ink_changed = Signal()
    space_requested = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.buffer = StrokeBuffer(settings.min_stroke_points)
        self.mouse_provider = MouseInputProvider()
        self.setMinimumHeight(260)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
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
        if event.button() == Qt.MouseButton.RightButton:
            self.space_requested.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.buffer.begin(self._to_point(event.position(), finger_down=True))
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.buffer.active_stroke is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.buffer.add(self._to_point(event.position(), finger_down=True))
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.buffer.active_stroke is not None:
            self.buffer.end(self._to_point(event.position(), finger_down=False))
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

    def _to_point(self, position: QPointF, *, finger_down: bool) -> Point:
        return self.mouse_provider.point(
            position.x(),
            position.y(),
            self.width(),
            self.height(),
            finger_down=finger_down,
        )
