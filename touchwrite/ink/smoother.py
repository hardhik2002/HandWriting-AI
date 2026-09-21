"""Conservative trajectory smoothing."""

from __future__ import annotations

from dataclasses import replace

from touchwrite.ink.models import Point, Stroke


class MovingAverageSmoother:
    def __init__(self, window_size: int = 3) -> None:
        if window_size < 1 or window_size % 2 == 0:
            raise ValueError("window_size must be a positive odd number")
        self.window_size = window_size

    def smooth(self, stroke: Stroke) -> Stroke:
        if self.window_size == 1 or len(stroke.points) < 3:
            return Stroke(stroke.stroke_id, list(stroke.points))
        radius = self.window_size // 2
        output: list[Point] = []
        for index, point in enumerate(stroke.points):
            if index in {0, len(stroke.points) - 1}:
                output.append(point)
                continue
            samples = stroke.points[max(0, index - radius) : index + radius + 1]
            output.append(
                replace(
                    point,
                    x=sum(sample.x for sample in samples) / len(samples),
                    y=sum(sample.y for sample in samples) / len(samples),
                )
            )
        return Stroke(stroke.stroke_id, output)

