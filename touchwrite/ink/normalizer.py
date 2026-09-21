"""Coordinate normalization utilities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CoordinateBounds:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def __post_init__(self) -> None:
        if self.max_x <= self.min_x or self.max_y <= self.min_y:
            raise ValueError("coordinate bounds must have positive width and height")

    def normalize(self, x_raw: float, y_raw: float) -> tuple[float, float]:
        x = (x_raw - self.min_x) / (self.max_x - self.min_x)
        y = (y_raw - self.min_y) / (self.max_y - self.min_y)
        return min(1.0, max(0.0, x)), min(1.0, max(0.0, y))

