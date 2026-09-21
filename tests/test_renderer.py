from __future__ import annotations

from tests.helpers import stroke
from touchwrite.ink.models import HandwrittenWord, Point, Stroke
from touchwrite.ink.renderer import (
    InkRenderer,
    bounding_box,
    filter_isolated_point_strokes,
)


def test_renderer_produces_expected_dimensions_and_ink() -> None:
    image = InkRenderer(width=128, height=64).render(HandwrittenWord([stroke()]))
    assert image.size == (128, 64)
    assert image.getextrema()[0] < 255


def test_empty_render_is_white_and_has_no_bounds() -> None:
    word = HandwrittenWord([])
    image = InkRenderer(width=80, height=40).render(word)
    assert image.getextrema() == (255, 255)
    assert bounding_box(word.strokes) is None


def test_bounding_box_uses_undistorted_raw_coordinates() -> None:
    misleading_normalized = Stroke(
        1,
        [
            Point(0.1, 0.1, 1, 10, 20),
            Point(0.2, 0.9, 2, 410, 120),
        ],
    )
    bounds = bounding_box([misleading_normalized])
    assert bounds is not None
    assert (bounds.max_x - bounds.min_x) / (bounds.max_y - bounds.min_y) == 4.0


def test_noise_filter_preserves_near_dot_and_raw_trajectory() -> None:
    body = Stroke(
        1,
        [
            Point(0.1, 0.2, 1, 10, 50),
            Point(0.5, 0.4, 2, 60, 50),
            Point(0.8, 0.8, 3, 110, 100),
        ],
    )
    near_dot = Stroke(2, [Point(0.5, 0.1, 4, 60, 25), Point(0.5, 0.1, 5, 60, 25)])
    far_click = Stroke(3, [Point(0.9, 0.5, 6, 250, 70), Point(0.9, 0.5, 7, 250, 70)])
    source = [body, near_dot, far_click]
    filtered = filter_isolated_point_strokes(source)
    assert [stroke.stroke_id for stroke in filtered] == [1, 2]
    assert len(source) == 3
    assert len(source[-1].points) == 2
