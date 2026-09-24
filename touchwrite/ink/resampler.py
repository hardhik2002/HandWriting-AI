"""Uniform spatial trajectory resampling that preserves strokes and detached marks."""

from __future__ import annotations

import math
from dataclasses import replace

from touchwrite.ink.models import Point, Stroke


def resample_stroke(stroke: Stroke, spacing: float) -> Stroke:
    if spacing <= 0:
        raise ValueError("spacing must be positive")
    if len(stroke.points) < 2:
        return Stroke(stroke.stroke_id, list(stroke.points))
    distances = [0.0]
    for previous, current in zip(stroke.points, stroke.points[1:], strict=False):
        distances.append(
            distances[-1]
            + math.hypot(current.x_raw - previous.x_raw, current.y_raw - previous.y_raw)
        )
    total = distances[-1]
    if total < spacing:
        return Stroke(stroke.stroke_id, list(stroke.points))
    targets = [index * spacing for index in range(int(total // spacing) + 1)]
    if targets[-1] < total:
        targets.append(total)
    output: list[Point] = []
    segment = 0
    for target in targets:
        while segment + 1 < len(distances) and distances[segment + 1] < target:
            segment += 1
        if segment + 1 >= len(stroke.points):
            output.append(stroke.points[-1])
            continue
        start = stroke.points[segment]
        end = stroke.points[segment + 1]
        span = distances[segment + 1] - distances[segment]
        ratio = 0.0 if span == 0 else (target - distances[segment]) / span
        output.append(_interpolate(start, end, ratio))
    return Stroke(stroke.stroke_id, output)


def resample_strokes(strokes: list[Stroke], spacing: float) -> list[Stroke]:
    return [resample_stroke(stroke, spacing) for stroke in strokes]


def _interpolate(start: Point, end: Point, ratio: float) -> Point:
    def value(left: float, right: float) -> float:
        return left + (right - left) * ratio

    display_x = None
    display_y = None
    if start.display_x is not None and end.display_x is not None:
        display_x = value(start.display_x, end.display_x)
    if start.display_y is not None and end.display_y is not None:
        display_y = value(start.display_y, end.display_y)
    return replace(
        start,
        x=value(start.x, end.x),
        y=value(start.y, end.y),
        x_raw=value(start.x_raw, end.x_raw),
        y_raw=value(start.y_raw, end.y_raw),
        timestamp_ns=round(value(start.timestamp_ns, end.timestamp_ns)),
        pressure=(
            value(start.pressure, end.pressure)
            if start.pressure is not None and end.pressure is not None
            else start.pressure
        ),
        finger_down=end.finger_down if ratio >= 1.0 else start.finger_down,
        display_x=display_x,
        display_y=display_y,
    )

