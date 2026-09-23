"""Direct absolute Qt touchscreen input translated into recognition-safe points."""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QSize

from touchwrite.ink.models import Point
from touchwrite.ui.coordinate_mapper import normalized_position


class TouchscreenInputProvider:
    """Track one writing contact while retaining the native contact identity."""

    name = "touchscreen"

    def __init__(self) -> None:
        self.active_contact_id: int | None = None

    def begin(
        self,
        contact_id: int,
        canvas_position: QPointF,
        canvas_size: QSize,
        *,
        pressure: float | None = None,
        timestamp_ns: int | None = None,
    ) -> Point | None:
        if self.active_contact_id is not None:
            return None
        self.active_contact_id = contact_id
        return self._point(
            contact_id,
            canvas_position,
            canvas_size,
            pressure=pressure,
            finger_down=True,
            timestamp_ns=timestamp_ns,
        )

    def update(
        self,
        contact_id: int,
        canvas_position: QPointF,
        canvas_size: QSize,
        *,
        pressure: float | None = None,
        timestamp_ns: int | None = None,
    ) -> Point | None:
        if contact_id != self.active_contact_id:
            return None
        return self._point(
            contact_id,
            canvas_position,
            canvas_size,
            pressure=pressure,
            finger_down=True,
            timestamp_ns=timestamp_ns,
        )

    def end(
        self,
        contact_id: int,
        canvas_position: QPointF,
        canvas_size: QSize,
        *,
        pressure: float | None = None,
        timestamp_ns: int | None = None,
    ) -> Point | None:
        if contact_id != self.active_contact_id:
            return None
        point = self._point(
            contact_id,
            canvas_position,
            canvas_size,
            pressure=pressure,
            finger_down=False,
            timestamp_ns=timestamp_ns,
        )
        self.active_contact_id = None
        return point

    def cancel(self) -> None:
        self.active_contact_id = None

    @staticmethod
    def _point(
        contact_id: int,
        canvas_position: QPointF,
        canvas_size: QSize,
        *,
        pressure: float | None,
        finger_down: bool,
        timestamp_ns: int | None,
    ) -> Point:
        x, y = normalized_position(canvas_position, canvas_size)
        return Point(
            x=x,
            y=y,
            x_raw=canvas_position.x(),
            y_raw=canvas_position.y(),
            timestamp_ns=timestamp_ns if timestamp_ns is not None else time.monotonic_ns(),
            pressure=pressure,
            contact_id=contact_id,
            finger_down=finger_down,
            display_x=canvas_position.x(),
            display_y=canvas_position.y(),
        )
