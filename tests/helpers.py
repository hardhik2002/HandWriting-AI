from __future__ import annotations

from touchwrite.ink.models import Point, Stroke


def point(x: float, y: float, timestamp_ns: int) -> Point:
    return Point(x, y, timestamp_ns, x, y)


def stroke(stroke_id: int = 1) -> Stroke:
    return Stroke(stroke_id, [point(0.1, 0.2, 1), point(0.8, 0.7, 2)])

