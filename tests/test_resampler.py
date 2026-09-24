from __future__ import annotations

from touchwrite.ink.models import Point, Stroke
from touchwrite.ink.resampler import resample_stroke


def test_uniform_resampling_preserves_endpoints_and_spacing() -> None:
    stroke = Stroke(
        1,
        [Point(0.0, 0.0, 0, 0, 0), Point(1.0, 0.0, 10_000_000, 10, 0)],
    )
    result = resample_stroke(stroke, 2.0)
    assert [point.x_raw for point in result.points] == [0, 2, 4, 6, 8, 10]
    assert result.points[0].timestamp_ns == 0
    assert result.points[-1].timestamp_ns == 10_000_000


def test_uniform_resampling_keeps_detached_dot_unchanged() -> None:
    dot = Stroke(
        2,
        [Point(0.5, 0.5, 1, 5, 5), Point(0.5, 0.5, 2, 5, 5)],
    )
    assert resample_stroke(dot, 2.0).points == dot.points

