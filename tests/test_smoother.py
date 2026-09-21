from __future__ import annotations

from tests.helpers import point
from touchwrite.ink.models import Stroke
from touchwrite.ink.smoother import MovingAverageSmoother


def test_smoothing_reduces_synthetic_jitter_and_preserves_ends() -> None:
    original = Stroke(
        1,
        [point(0.0, 0.5, 1), point(0.25, 0.8, 2), point(0.5, 0.2, 3), point(1.0, 0.5, 4)],
    )
    smoothed = MovingAverageSmoother(3).smooth(original)
    assert smoothed.points[0] == original.points[0]
    assert smoothed.points[-1] == original.points[-1]
    assert abs(smoothed.points[1].y - 0.5) < abs(original.points[1].y - 0.5)

