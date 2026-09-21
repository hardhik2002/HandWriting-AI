"""Mutable capture buffer that preserves complete online trajectories."""

from __future__ import annotations

import math
from dataclasses import replace

from touchwrite.ink.models import HandwrittenWord, Point, Stroke


class StrokeBuffer:
    def __init__(self, minimum_points: int = 2) -> None:
        self.minimum_points = minimum_points
        self._strokes: list[Stroke] = []
        self._active: Stroke | None = None
        self._next_id = 1

    @property
    def strokes(self) -> tuple[Stroke, ...]:
        return tuple(self._strokes)

    @property
    def active_stroke(self) -> Stroke | None:
        return self._active

    @property
    def is_empty(self) -> bool:
        return not self._strokes and self._active is None

    def begin(self, point: Point) -> None:
        if self._active is not None:
            raise RuntimeError("a stroke is already active")
        self._active = Stroke(self._next_id, [point])
        self._next_id += 1

    def add(self, point: Point) -> None:
        if self._active is None:
            raise RuntimeError("cannot add a point without an active stroke")
        previous = self._active.points[-1]
        dt_seconds = max((point.timestamp_ns - previous.timestamp_ns) / 1_000_000_000, 0.0)
        dx, dy = point.x - previous.x, point.y - previous.y
        distance = math.hypot(dx, dy)
        enriched = replace(
            point,
            dx=dx,
            dy=dy,
            velocity=distance / dt_seconds if dt_seconds > 0 else 0.0,
        )
        self._active.points.append(enriched)

    def end(self, point: Point | None = None) -> Stroke | None:
        if self._active is None:
            return None
        if point is not None:
            last = self._active.points[-1]
            if (point.x, point.y, point.timestamp_ns) != (last.x, last.y, last.timestamp_ns):
                self.add(point)
        stroke = self._active
        self._active = None
        if len(stroke.points) >= self.minimum_points:
            self._strokes.append(stroke)
            return stroke
        return None

    def finalize_active(self) -> Stroke | None:
        return self.end()

    def undo(self) -> Stroke | None:
        if self._active is not None:
            stroke, self._active = self._active, None
            return stroke
        return self._strokes.pop() if self._strokes else None

    def clear(self) -> list[Stroke]:
        previous = self.snapshot().strokes
        self._strokes = []
        self._active = None
        return previous

    def snapshot(self) -> HandwrittenWord:
        strokes = [Stroke(item.stroke_id, list(item.points)) for item in self._strokes]
        if self._active is not None:
            strokes.append(Stroke(self._active.stroke_id, list(self._active.points)))
        return HandwrittenWord(strokes=strokes)

    def restore(self, word: HandwrittenWord) -> None:
        self._strokes = [Stroke(item.stroke_id, list(item.points)) for item in word.strokes]
        self._active = None
        self._next_id = max((stroke.stroke_id for stroke in self._strokes), default=0) + 1

