from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QEventPoint, QTouchEvent

from touchwrite.input.touchscreen_provider import TouchscreenInputProvider


def test_touch_begin_update_end_preserve_absolute_logical_coordinates() -> None:
    provider = TouchscreenInputProvider()
    size = QSize(1000, 500)
    begin = provider.begin(7, QPointF(650, 420), size, pressure=0.4, timestamp_ns=1)
    update = provider.update(7, QPointF(660, 425), size, pressure=0.5, timestamp_ns=2)
    end = provider.end(7, QPointF(670, 430), size, pressure=0.0, timestamp_ns=3)

    assert begin is not None and update is not None and end is not None
    assert (begin.x_raw, begin.y_raw) == (650, 420)
    assert (begin.display_x, begin.display_y) == (650, 420)
    assert (begin.x, begin.y) == (0.65, 0.84)
    assert begin.contact_id == update.contact_id == end.contact_id == 7
    assert end.finger_down is False


def test_secondary_contacts_do_not_duplicate_the_writing_stroke() -> None:
    provider = TouchscreenInputProvider()
    size = QSize(800, 600)
    assert provider.begin(11, QPointF(100, 100), size) is not None
    assert provider.begin(12, QPointF(200, 200), size) is None
    assert provider.update(12, QPointF(220, 220), size) is None
    assert provider.end(12, QPointF(240, 240), size) is None
    assert provider.update(11, QPointF(110, 110), size) is not None
    assert provider.end(11, QPointF(120, 120), size) is not None
    assert provider.begin(12, QPointF(200, 200), size) is not None


class _SyntheticMouseEvent:
    @staticmethod
    def source():
        return Qt.MouseEventSource.MouseEventSynthesizedByQt

    @staticmethod
    def pointingDevice():  # noqa: N802
        return None


def test_canvas_rejects_synthesized_mouse_when_touchscreen_mode(qtbot) -> None:
    from touchwrite.config.settings import Settings
    from touchwrite.ui.ink_canvas import InkCanvas

    canvas = InkCanvas(Settings(save_samples=False, autosave_enabled=False))
    qtbot.addWidget(canvas)
    canvas.set_input_mode("touchscreen")
    assert canvas._reject_synthesized_touch_mouse(_SyntheticMouseEvent())  # type: ignore[arg-type]


def test_canvas_handles_native_touch_phases_without_coordinate_translation(qtbot) -> None:
    from touchwrite.config.settings import Settings
    from touchwrite.ui.ink_canvas import InkCanvas

    canvas = InkCanvas(Settings(save_samples=False, autosave_enabled=False))
    canvas.resize(800, 600)
    canvas.set_input_mode("touchscreen")
    qtbot.addWidget(canvas)
    canvas.show()
    qtbot.waitExposed(canvas)
    origin = canvas.mapToGlobal(QPoint(0, 0))

    def send(event_type: QEvent.Type, state: QEventPoint.State, local: QPointF) -> None:
        global_position = QPointF(origin.x() + local.x(), origin.y() + local.y())
        point = QEventPoint(
            21,
            state,
            local,
            global_position,
        )
        QCoreApplication.sendEvent(canvas, QTouchEvent(event_type, touchPoints=[point]))

    send(QEvent.Type.TouchBegin, QEventPoint.State.Pressed, QPointF(300, 250))
    send(QEvent.Type.TouchUpdate, QEventPoint.State.Updated, QPointF(320, 265))
    send(QEvent.Type.TouchEnd, QEventPoint.State.Released, QPointF(340, 280))

    assert len(canvas.strokes) == 1
    positions = [(point.x_raw, point.y_raw) for point in canvas.strokes[0].points]
    assert positions == [(300, 250), (320, 265), (340, 280)]
    assert [
        (point.display_x, point.display_y) for point in canvas.strokes[0].points
    ] == positions


def test_touch_begin_outside_active_canvas_does_not_create_stroke(qtbot) -> None:
    from touchwrite.config.settings import Settings
    from touchwrite.ui.ink_canvas import InkCanvas

    canvas = InkCanvas(Settings(save_samples=False, autosave_enabled=False))
    canvas.resize(800, 600)
    canvas.set_input_mode("touchscreen")
    qtbot.addWidget(canvas)
    canvas.show()
    qtbot.waitExposed(canvas)
    origin = canvas.mapToGlobal(QPoint(0, 0))
    local = QPointF(2, 2)
    point = QEventPoint(
        3,
        QEventPoint.State.Pressed,
        local,
        QPointF(origin.x() + 2, origin.y() + 2),
    )
    QCoreApplication.sendEvent(
        canvas,
        QTouchEvent(QEvent.Type.TouchBegin, touchPoints=[point]),
    )
    assert canvas.buffer.is_empty
