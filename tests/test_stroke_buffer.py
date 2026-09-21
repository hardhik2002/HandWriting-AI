from __future__ import annotations

from tests.helpers import point
from touchwrite.ink.normalizer import CoordinateBounds
from touchwrite.ink.stroke_buffer import StrokeBuffer


def test_one_and_multiple_strokes_are_preserved() -> None:
    buffer = StrokeBuffer()
    buffer.begin(point(0.1, 0.1, 1))
    buffer.end(point(0.2, 0.2, 2))
    buffer.begin(point(0.5, 0.5, 3))
    buffer.end(point(0.6, 0.6, 4))
    assert [stroke.stroke_id for stroke in buffer.strokes] == [1, 2]
    assert buffer.strokes[0].points[-1].velocity > 0


def test_undo_clear_and_restore() -> None:
    buffer = StrokeBuffer()
    buffer.begin(point(0.1, 0.1, 1))
    buffer.end(point(0.2, 0.2, 2))
    snapshot = buffer.snapshot()
    assert buffer.undo() is not None
    assert buffer.is_empty
    buffer.restore(snapshot)
    assert len(buffer.strokes) == 1
    assert len(buffer.clear()) == 1


def test_normalization_clamps_coordinates() -> None:
    bounds = CoordinateBounds(10, 20, 110, 220)
    assert bounds.normalize(60, 120) == (0.5, 0.5)
    assert bounds.normalize(-50, 500) == (0.0, 1.0)

