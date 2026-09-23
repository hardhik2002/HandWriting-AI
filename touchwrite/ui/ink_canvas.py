"""Layered document canvas with direct mouse and native Qt touchscreen input."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QEventPoint,
    QFont,
    QFontMetricsF,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPointingDevice,
    QTouchEvent,
)
from PySide6.QtWidgets import QAbstractScrollArea, QWidget

from touchwrite.config.settings import Settings
from touchwrite.document.models import WhiteboardDocument
from touchwrite.ink.models import HandwrittenWord, Point, Stroke
from touchwrite.ink.stroke_buffer import StrokeBuffer
from touchwrite.input.mouse_provider import MouseInputProvider
from touchwrite.input.touch_diagnostics import TouchDiagnosticRecord, TouchDiagnostics
from touchwrite.input.touchscreen_provider import TouchscreenInputProvider
from touchwrite.ui.coordinate_mapper import canvas_to_document, clamp_to_rect, global_to_canvas


@dataclass(frozen=True, slots=True)
class _PendingDiagnostic:
    event_type: str
    contact_id: int
    event_timestamp_ns: int
    event_local: QPointF
    event_global: QPointF
    transformed_canvas: QPointF
    paint_position: QPointF
    device_type: str


class InkCanvas(QWidget):
    """Paint direct ink at input coordinates while retaining undistorted OCR geometry."""

    ink_changed = Signal()
    stroke_started = Signal()
    stroke_ended = Signal()
    space_requested = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.input_mode = settings.input_mode
        self.buffer = StrokeBuffer(settings.min_stroke_points)
        self.document = WhiteboardDocument()
        self.preview_text = ""
        self.pointer_to_ink_latency_ms = 0.0
        self.mouse_provider = MouseInputProvider()
        self.touchscreen_provider = TouchscreenInputProvider()
        diagnostics_path = (
            settings.touchscreen_debug_dir / "events.jsonl" if settings.debug_input else None
        )
        self.touch_diagnostics = TouchDiagnostics(diagnostics_path)
        self._pending_diagnostics: list[_PendingDiagnostic] = []
        self._last_touch_event_ns = 0
        self._last_diagnostic_position: QPointF | None = None
        self._last_diagnostic_transformed: QPointF | None = None
        self.setMinimumSize(760, 620)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor("white"))
        self.setPalette(palette)

    @property
    def strokes(self) -> tuple[Stroke, ...]:
        return self.buffer.strokes

    def snapshot(self) -> HandwrittenWord:
        return self.buffer.snapshot()

    @property
    def input_active(self) -> bool:
        return (
            self.buffer.active_stroke is not None
            or self.touchscreen_provider.active_contact_id is not None
        )

    def active_writing_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(24.0, 18.0, -24.0, -18.0)

    def set_input_mode(self, mode: str) -> None:
        self.input_mode = mode
        if mode != "touchscreen":
            self.touchscreen_provider.cancel()

    def set_document(self, document: WhiteboardDocument) -> None:
        self.document = document
        self.setMinimumHeight(max(620, 100 + len(document.lines) * 72))
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
        self.touchscreen_provider.cancel()
        self.update()
        self.ink_changed.emit()

    def undo_stroke(self) -> None:
        self.buffer.undo()
        self.touchscreen_provider.cancel()
        self.update()
        self.ink_changed.emit()

    def event(self, event: QEvent) -> bool:
        if (
            event.type()
            in {
            QEvent.Type.TouchBegin,
            QEvent.Type.TouchUpdate,
            QEvent.Type.TouchEnd,
            QEvent.Type.TouchCancel,
            }
            and self.input_mode == "touchscreen"
            and isinstance(event, QTouchEvent)
        ):
            self._handle_touch_event(event)
            return True
        return super().event(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._reject_synthesized_touch_mouse(event):
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.space_requested.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            position = canvas_to_document(event.position())
            if not self.active_writing_rect().contains(position):
                event.accept()
                return
            self.buffer.begin(self._mouse_point(position, finger_down=True))
            self.stroke_started.emit()
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._reject_synthesized_touch_mouse(event):
            event.accept()
            return
        if self.buffer.active_stroke is not None and event.buttons() & Qt.MouseButton.LeftButton:
            position = clamp_to_rect(
                canvas_to_document(event.position()), self.active_writing_rect()
            )
            self.buffer.add(self._mouse_point(position, finger_down=True))
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._reject_synthesized_touch_mouse(event):
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.buffer.active_stroke is not None:
            position = clamp_to_rect(
                canvas_to_document(event.position()), self.active_writing_rect()
            )
            self.buffer.end(self._mouse_point(position, finger_down=False))
            self.update()
            self.ink_changed.emit()
            self.stroke_ended.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: object) -> None:  # noqa: N802, ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#eef2f7"))
        page = self.rect().adjusted(18, 12, -18, -12)
        painter.fillRect(page, QColor("white"))
        self._paint_document(painter)
        painter.save()
        painter.setClipRect(self.active_writing_rect())
        painter.setPen(
            QPen(
                QColor("#111827"),
                self.settings.visual_stroke_width,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        strokes = list(self.buffer.strokes)
        if self.buffer.active_stroke is not None:
            strokes.append(self.buffer.active_stroke)
        for stroke in strokes:
            positions = [self._display_position(point) for point in stroke.points]
            if len(positions) == 1:
                painter.drawPoint(positions[0])
            elif positions:
                path = QPainterPath(positions[0])
                for position in positions[1:]:
                    path.lineTo(position)
                painter.drawPath(path)
        painter.restore()
        cursor_x, cursor_y = self.cursor_position()
        if self.preview_text:
            painter.setPen(QColor("#64748b"))
            preview_font = QFont("Segoe UI", 12)
            preview_font.setItalic(True)
            painter.setFont(preview_font)
            painter.drawText(QPointF(cursor_x, cursor_y + 22), self.preview_text)
        if self.settings.debug_input:
            self._paint_diagnostic_overlay(painter)
        self._flush_paint_diagnostics(time.perf_counter_ns())

    def cursor_position(self) -> tuple[float, float]:
        margin_x = 56.0
        baseline = 82.0 + self.document.current_line_index * 72.0
        metrics = QFontMetricsF(QFont("Segoe UI", 22))
        x = margin_x
        for word in self.document.current_line.words:
            x += float(metrics.horizontalAdvance(word.display_text)) + 14.0
        if self.document.current_line.trailing_space:
            x += 8.0
        return x, baseline

    def _paint_document(self, painter: QPainter) -> None:
        font = QFont("Segoe UI", 22)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        for line_index, line in enumerate(self.document.lines):
            baseline = 82.0 + line_index * 72.0
            painter.setPen(QPen(QColor("#e7edf4"), 1))
            painter.drawLine(QPointF(42, baseline + 12), QPointF(self.width() - 42, baseline + 12))
            x = 56.0
            for word in line.words:
                painter.setPen(QColor("#94a3b8") if word.text is None else QColor("#111827"))
                painter.drawText(QPointF(x, baseline), word.display_text)
                x += float(metrics.horizontalAdvance(word.display_text)) + 14.0
            if line_index == self.document.current_line_index:
                painter.setPen(QPen(QColor("#2563eb"), 2))
                painter.drawLine(QPointF(x, baseline - 30), QPointF(x, baseline + 8))

    def _handle_touch_event(self, event: QTouchEvent) -> None:
        arrival_ns = time.perf_counter_ns()
        self._last_touch_event_ns = arrival_ns
        event_type = event.type()
        if event_type == QEvent.Type.TouchCancel:
            self.buffer.finalize_active()
            self.touchscreen_provider.cancel()
            self.ink_changed.emit()
            self.stroke_ended.emit()
            event.accept()
            return
        for event_point in event.points():
            state = event_point.state()
            event_position = event_point.position()
            if event_position.isNull() and not event_point.scenePosition().isNull():
                # Programmatically constructed Qt test events expose only scenePosition.
                event_position = event_point.scenePosition()
            local = canvas_to_document(event_position)
            global_position = event_point.globalPosition()
            transformed = global_to_canvas(self, global_position)
            pressure = event_point.pressure()
            timestamp_ns = arrival_ns
            point: Point | None = None
            if state == QEventPoint.State.Pressed:
                if not self.active_writing_rect().contains(local):
                    continue
                point = self.touchscreen_provider.begin(
                    event_point.id(),
                    local,
                    self.size(),
                    pressure=pressure,
                    timestamp_ns=timestamp_ns,
                )
                if point is not None:
                    self.buffer.begin(point)
                    self.stroke_started.emit()
            elif state == QEventPoint.State.Updated:
                local = clamp_to_rect(local, self.active_writing_rect())
                point = self.touchscreen_provider.update(
                    event_point.id(),
                    local,
                    self.size(),
                    pressure=pressure,
                    timestamp_ns=timestamp_ns,
                )
                if point is not None and self.buffer.active_stroke is not None:
                    self.buffer.add(point)
            elif state == QEventPoint.State.Released:
                local = clamp_to_rect(local, self.active_writing_rect())
                point = self.touchscreen_provider.end(
                    event_point.id(),
                    local,
                    self.size(),
                    pressure=pressure,
                    timestamp_ns=timestamp_ns,
                )
                if point is not None and self.buffer.active_stroke is not None:
                    self.buffer.end(point)
                    self.ink_changed.emit()
                    self.stroke_ended.emit()
            if point is not None:
                self._queue_diagnostic(
                    event,
                    event_point.id(),
                    arrival_ns,
                    local,
                    global_position,
                    transformed,
                    self._display_position(point),
                )
        self.update()
        event.accept()

    def _mouse_point(self, position: QPointF, *, finger_down: bool) -> Point:
        return self.mouse_provider.point(
            position.x(),
            position.y(),
            self.width(),
            self.height(),
            finger_down=finger_down,
        )

    def _reject_synthesized_touch_mouse(self, event: QMouseEvent) -> bool:
        if self.input_mode != "touchscreen":
            return False
        synthesized = event.source() != Qt.MouseEventSource.MouseEventNotSynthesized
        device = event.pointingDevice()
        from_touchscreen = (
            device is not None and device.type() == QPointingDevice.DeviceType.TouchScreen
        )
        return synthesized or from_touchscreen

    @staticmethod
    def _display_position(point: Point) -> QPointF:
        return QPointF(
            point.display_x if point.display_x is not None else point.x_raw,
            point.display_y if point.display_y is not None else point.y_raw,
        )

    def _queue_diagnostic(
        self,
        event: QTouchEvent,
        contact_id: int,
        timestamp_ns: int,
        local: QPointF,
        global_position: QPointF,
        transformed: QPointF,
        paint_position: QPointF,
    ) -> None:
        self._last_diagnostic_position = QPointF(local)
        self._last_diagnostic_transformed = QPointF(transformed)
        device = event.pointingDevice()
        self._pending_diagnostics.append(
            _PendingDiagnostic(
                event.type().name,
                contact_id,
                timestamp_ns,
                QPointF(local),
                QPointF(global_position),
                QPointF(transformed),
                QPointF(paint_position),
                device.type().name if device is not None else "Unknown",
            )
        )

    def _flush_paint_diagnostics(self, paint_timestamp_ns: int) -> None:
        if not self._pending_diagnostics:
            return
        viewport, scroll_offset = self._viewport_details()
        canvas_geometry = self.geometry()
        screen = self.screen()
        for pending in self._pending_diagnostics:
            error = math.hypot(
                pending.transformed_canvas.x() - pending.paint_position.x(),
                pending.transformed_canvas.y() - pending.paint_position.y(),
            )
            viewport_geometry = None
            if viewport is not None:
                geometry = viewport.geometry()
                viewport_geometry = (
                    geometry.x(),
                    geometry.y(),
                    geometry.width(),
                    geometry.height(),
                )
            self.touch_diagnostics.add(
                TouchDiagnosticRecord(
                    event_type=pending.event_type,
                    contact_id=pending.contact_id,
                    event_timestamp_ns=pending.event_timestamp_ns,
                    paint_timestamp_ns=paint_timestamp_ns,
                    event_local=(pending.event_local.x(), pending.event_local.y()),
                    event_global=(pending.event_global.x(), pending.event_global.y()),
                    transformed_canvas=(
                        pending.transformed_canvas.x(),
                        pending.transformed_canvas.y(),
                    ),
                    paint_position=(pending.paint_position.x(), pending.paint_position.y()),
                    positional_error_px=error,
                    device_type=pending.device_type,
                    device_pixel_ratio=self.devicePixelRatioF(),
                    screen_device_pixel_ratio=(
                        screen.devicePixelRatio() if screen is not None else 1.0
                    ),
                    canvas_geometry=(
                        canvas_geometry.x(),
                        canvas_geometry.y(),
                        canvas_geometry.width(),
                        canvas_geometry.height(),
                    ),
                    viewport_geometry=viewport_geometry,
                    scroll_offset=scroll_offset,
                )
            )
        self.pointer_to_ink_latency_ms = max(
            0.0,
            (paint_timestamp_ns - self._pending_diagnostics[-1].event_timestamp_ns) / 1_000_000,
        )
        self._pending_diagnostics.clear()

    def _viewport_details(self) -> tuple[QWidget | None, tuple[int, int] | None]:
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                return (
                    parent.viewport(),
                    (
                        parent.horizontalScrollBar().value(),
                        parent.verticalScrollBar().value(),
                    ),
                )
            parent = parent.parentWidget()
        return None, None

    def _paint_diagnostic_overlay(self, painter: QPainter) -> None:
        if self._last_diagnostic_position is None or self._last_diagnostic_transformed is None:
            return
        painter.setPen(QPen(QColor("#dc2626"), 2))
        self._draw_crosshair(painter, self._last_diagnostic_position, 10)
        painter.setPen(QPen(QColor("#16a34a"), 1))
        self._draw_crosshair(painter, self._last_diagnostic_transformed, 6)
        painter.setPen(QColor("#334155"))
        text_position = self._last_diagnostic_position + QPointF(12, -12)
        painter.drawText(
            text_position,
            f"local {self._last_diagnostic_position.x():.1f}, "
            f"{self._last_diagnostic_position.y():.1f}",
        )

    @staticmethod
    def _draw_crosshair(painter: QPainter, position: QPointF, radius: float) -> None:
        painter.drawLine(
            QPointF(position.x() - radius, position.y()),
            QPointF(position.x() + radius, position.y()),
        )
        painter.drawLine(
            QPointF(position.x(), position.y() - radius),
            QPointF(position.x(), position.y() + radius),
        )
