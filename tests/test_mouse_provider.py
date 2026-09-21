from __future__ import annotations

from touchwrite.input.mouse_provider import MouseInputProvider


def test_mouse_provider_preserves_raw_and_normalized_coordinates() -> None:
    provider = MouseInputProvider()
    point = provider.point(25, 75, 100, 100, finger_down=False, timestamp_ns=123)
    assert (point.x, point.y) == (0.25, 0.75)
    assert (point.x_raw, point.y_raw) == (25, 75)
    assert point.timestamp_ns == 123
    assert point.finger_down is False
