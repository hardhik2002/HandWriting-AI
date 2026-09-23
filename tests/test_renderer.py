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


def test_golden_processed_image_is_unchanged_when_local_fixture_exists() -> None:
    from pathlib import Path

    import pytest
    from PIL import Image, ImageChops

    from touchwrite.config.settings import Settings
    from touchwrite.ink.smoother import MovingAverageSmoother
    from touchwrite.persistence.session_store import SessionStore

    sample_id = "ba216970-66de-4d3e-b192-7669dd273b86"
    sample_dir = Path("data/handwriting") / sample_id
    if not (sample_dir / "trajectory.json").is_file():
        pytest.skip("local golden handwriting fixture is not installed")
    settings = Settings()
    word = SessionStore(settings.data_dir).load(sample_id)
    smoother = MovingAverageSmoother(settings.smoothing_window)
    processed_word = HandwrittenWord(
        [smoother.smooth(item) for item in word.strokes],
        word_id=word.word_id,
        created_at=word.created_at,
    )
    actual = InkRenderer(
        settings.render_width,
        settings.render_height,
        settings.render_padding,
        settings.stroke_width,
    ).render(processed_word, filter_noise=True)
    with Image.open(sample_dir / "processed.png") as source_image:
        expected = source_image.convert("L")
    assert ImageChops.difference(actual, expected).getbbox() is None
