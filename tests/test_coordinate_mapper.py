from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtWidgets import QScrollArea, QWidget

from touchwrite.ui.coordinate_mapper import (
    canvas_to_document,
    document_to_view,
    global_to_canvas,
    viewport_to_canvas,
)


def test_global_to_canvas_uses_current_widget_geometry(qtbot) -> None:
    window = QWidget()
    window.resize(600, 400)
    canvas = QWidget(window)
    canvas.setGeometry(75, 55, 300, 200)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)

    expected = QPointF(120.5, 80.25)
    origin = canvas.mapToGlobal(QPoint(0, 0))
    global_position = QPointF(origin.x() + expected.x(), origin.y() + expected.y())
    assert global_to_canvas(canvas, global_position) == expected

    canvas.move(105, 85)
    origin = canvas.mapToGlobal(QPoint(0, 0))
    moved_global = QPointF(origin.x() + expected.x(), origin.y() + expected.y())
    assert global_to_canvas(canvas, moved_global) == expected


def test_viewport_canvas_document_mapping_includes_scroll_offset(qtbot) -> None:
    scroll = QScrollArea()
    scroll.resize(320, 220)
    canvas = QWidget()
    canvas.resize(900, 700)
    canvas.setMinimumSize(900, 700)
    scroll.setWidget(canvas)
    scroll.setWidgetResizable(False)
    qtbot.addWidget(scroll)
    scroll.show()
    qtbot.waitExposed(scroll)
    scroll.horizontalScrollBar().setValue(140)
    scroll.verticalScrollBar().setValue(95)

    viewport_position = QPointF(80, 60)
    mapped = viewport_to_canvas(scroll.viewport(), canvas, viewport_position)
    expected = canvas.mapFrom(
        scroll.viewport(), QPoint(int(viewport_position.x()), int(viewport_position.y()))
    )
    assert mapped == QPointF(expected)
    assert canvas_to_document(mapped) == mapped
    assert document_to_view(scroll.viewport(), canvas, mapped) == viewport_position


def test_mapping_queries_resize_instead_of_caching_dimensions(qtbot) -> None:
    canvas = QWidget()
    qtbot.addWidget(canvas)
    canvas.resize(200, 100)
    canvas.show()
    qtbot.waitExposed(canvas)
    origin = canvas.mapToGlobal(QPoint(0, 0))
    assert global_to_canvas(canvas, QPointF(origin.x() + 199, origin.y() + 99)) == QPointF(
        199, 99
    )
    canvas.resize(500, 350)
    origin = canvas.mapToGlobal(QPoint(0, 0))
    assert global_to_canvas(canvas, QPointF(origin.x() + 499, origin.y() + 349)) == QPointF(
        499, 349
    )
