"""Explicit mappings between Qt global, viewport, canvas, and document coordinates."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize
from PySide6.QtWidgets import QWidget


def global_to_canvas(canvas: QWidget, global_position: QPointF) -> QPointF:
    """Map a Qt logical global position into canvas-local logical coordinates."""
    global_origin = canvas.mapToGlobal(QPoint(0, 0))
    return QPointF(
        global_position.x() - global_origin.x(),
        global_position.y() - global_origin.y(),
    )


def viewport_to_canvas(
    viewport: QWidget,
    canvas: QWidget,
    viewport_position: QPointF,
) -> QPointF:
    """Map viewport-local logical coordinates through the real widget hierarchy."""
    viewport_origin = viewport.mapToGlobal(QPoint(0, 0))
    global_position = QPointF(
        viewport_origin.x() + viewport_position.x(),
        viewport_origin.y() + viewport_position.y(),
    )
    return global_to_canvas(canvas, global_position)


def canvas_to_document(canvas_position: QPointF) -> QPointF:
    """The scroll content widget is the document, so this transform is intentionally identity."""
    return QPointF(canvas_position)


def document_to_view(
    viewport: QWidget,
    canvas: QWidget,
    document_position: QPointF,
) -> QPointF:
    """Map a document/canvas point to viewport-local logical coordinates."""
    canvas_origin = canvas.mapToGlobal(QPoint(0, 0))
    viewport_origin = viewport.mapToGlobal(QPoint(0, 0))
    return QPointF(
        canvas_origin.x() + document_position.x() - viewport_origin.x(),
        canvas_origin.y() + document_position.y() - viewport_origin.y(),
    )


def normalized_position(position: QPointF, size: QSize) -> tuple[float, float]:
    """Store bounded convenience coordinates without using them as recognition geometry."""
    width = max(1, size.width())
    height = max(1, size.height())
    return (
        min(1.0, max(0.0, position.x() / width)),
        min(1.0, max(0.0, position.y() / height)),
    )


def clamp_to_rect(position: QPointF, bounds: QRectF) -> QPointF:
    return QPointF(
        min(bounds.right(), max(bounds.left(), position.x())),
        min(bounds.bottom(), max(bounds.top(), position.y())),
    )
