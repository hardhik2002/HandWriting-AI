"""Window-local mouse fallback translated into the common ink point model."""

from __future__ import annotations

import time

from touchwrite.ink.models import Point


class MouseInputProvider:
    name = "mouse"

    def point(
        self,
        x_raw: float,
        y_raw: float,
        width: int,
        height: int,
        *,
        finger_down: bool,
        timestamp_ns: int | None = None,
    ) -> Point:
        safe_width = max(1, width)
        safe_height = max(1, height)
        return Point(
            x=min(1.0, max(0.0, x_raw / safe_width)),
            y=min(1.0, max(0.0, y_raw / safe_height)),
            x_raw=x_raw,
            y_raw=y_raw,
            timestamp_ns=timestamp_ns if timestamp_ns is not None else time.monotonic_ns(),
            contact_id=0,
            finger_down=finger_down,
        )

