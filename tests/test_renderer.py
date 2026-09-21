from __future__ import annotations

from tests.helpers import stroke
from touchwrite.ink.models import HandwrittenWord
from touchwrite.ink.renderer import InkRenderer, bounding_box


def test_renderer_produces_expected_dimensions_and_ink() -> None:
    image = InkRenderer(width=128, height=64).render(HandwrittenWord([stroke()]))
    assert image.size == (128, 64)
    assert image.getextrema()[0] < 255


def test_empty_render_is_white_and_has_no_bounds() -> None:
    word = HandwrittenWord([])
    image = InkRenderer(width=80, height=40).render(word)
    assert image.getextrema() == (255, 255)
    assert bounding_box(word.strokes) is None

