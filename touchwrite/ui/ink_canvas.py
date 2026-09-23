"""Layered document and real-time ink whiteboard."""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from touchwrite.config.settings import Settings
from touchwrite.document.models import WhiteboardDocument
from touchwrite.ink.models import HandwrittenWord, Point, Stroke
from touchwrite.ink.stroke_buffer import StrokeBuffer
from touchwrite.input.mouse_provider import MouseInputProvider


class InkCanvas(QWidget):
    """Capture and render mouse strokes without blocking the UI thread."""

    ink_changed = Signal()
    stroke_started = Signal()
    space_requested = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.buffer = StrokeBuffer(settings.min_stroke_points)
        self.document = WhiteboardDocument()
        self.preview_text = ""
        self.pointer_to_ink_latency_ms = 0.0
        self._last_pointer_event_at: float | None = None
        self.mouse_provider = MouseInputProvider()
        self.setMinimumSize(760, 720)
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

    def set_document(self, document: WhiteboardDocument) -> None:
        self.document = document
        self.setMinimumHeight(max(720, 100 + len(document.lines) * 72))
        self.updateGeometry()
        self.update()

    def set_preview(self, text: str) -> None:
        self.preview_text = text
        self.update()

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
            self._last_pointer_event_at = time.perf_counter()
            self.stroke_started.emit()
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.buffer.active_stroke is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.buffer.add(self._to_point(event.position(), finger_down=True))
            self._last_pointer_event_at = time.perf_counter()
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
        painter.fillRect(self.rect(), QColor("#f3f4f6"))
        page = self.rect().adjusted(18, 16, -18, -16)
        painter.fillRect(page, QColor("white"))
        self._paint_document(painter)
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
        cursor_x, cursor_y = self.cursor_position()
        first_point = next(
            (point for stroke in strokes for point in stroke.points),
            None,
        )
        translate_x = cursor_x - first_point.x_raw if first_point is not None else 0.0
        translate_y = cursor_y - 38 - first_point.y_raw if first_point is not None else 0.0
        for stroke in strokes:
            if not stroke.points:
                continue
            positions = [
                QPointF(point.x_raw + translate_x, point.y_raw + translate_y)
                for point in stroke.points
            ]
            if len(positions) == 1:
                painter.drawPoint(positions[0])
                continue
            path = QPainterPath(positions[0])
            for position in positions[1:]:
                path.lineTo(position)
            painter.drawPath(path)
        if self.preview_text:
            painter.setPen(QColor("#64748b"))
            preview_font = QFont("Segoe UI", 12)
            preview_font.setItalic(True)
            painter.setFont(preview_font)
            painter.drawText(QPointF(cursor_x, cursor_y + 22), self.preview_text)
        if self._last_pointer_event_at is not None:
            self.pointer_to_ink_latency_ms = (
                time.perf_counter() - self._last_pointer_event_at
            ) * 1000
            self._last_pointer_event_at = None

    def cursor_position(self) -> tuple[float, float]:
        margin_x = 56.0
        baseline = 82.0 + self.document.current_line_index * 72.0
        font = QFont("Segoe UI", 22)
        metrics = self.fontMetrics() if self.font() == font else None
        if metrics is None:
            from PySide6.QtGui import QFontMetricsF

            metrics = QFontMetricsF(font)
        x = margin_x
        for word in self.document.current_line.words:
            x += float(metrics.horizontalAdvance(word.display_text)) + 14.0
        if self.document.current_line.trailing_space:
            x += 8.0
        return x, baseline

    def _paint_document(self, painter: QPainter) -> None:
        font = QFont("Segoe UI", 22)
        painter.setFont(font)
        from PySide6.QtGui import QFontMetricsF

        metrics = QFontMetricsF(font)
        for line_index, line in enumerate(self.document.lines):
            baseline = 82.0 + line_index * 72.0
            painter.setPen(QPen(QColor("#edf1f5"), 1))
            painter.drawLine(QPointF(42, baseline + 12), QPointF(self.width() - 42, baseline + 12))
            x = 56.0
            for word in line.words:
                painter.setPen(QColor("#94a3b8") if word.text is None else QColor("#111827"))
                painter.drawText(QPointF(x, baseline), word.display_text)
                x += float(metrics.horizontalAdvance(word.display_text)) + 14.0
            if line_index == self.document.current_line_index:
                painter.setPen(QPen(QColor("#2563eb"), 2))
                painter.drawLine(QPointF(x, baseline - 30), QPointF(x, baseline + 8))

    def _to_point(self, position: QPointF, *, finger_down: bool) -> Point:
        return self.mouse_provider.point(
            position.x(),
            position.y(),
            self.width(),
            self.height(),
            finger_down=finger_down,
        )
