from __future__ import annotations

from touchwrite.input.base import ContactEvent, ContactPhase, GestureAction
from touchwrite.input.gesture_engine import GestureEngine


def event(phase: ContactPhase, contact: int, x: float, y: float, ms: int) -> ContactEvent:
    return ContactEvent(phase, contact, x, y, ms * 1_000_000)


def test_valid_two_finger_tap() -> None:
    engine = GestureEngine()
    events = [
        event(ContactPhase.DOWN, 1, 0.2, 0.2, 0),
        event(ContactPhase.DOWN, 2, 0.7, 0.2, 5),
        event(ContactPhase.UP, 1, 0.205, 0.2, 80),
        event(ContactPhase.UP, 2, 0.7, 0.205, 85),
    ]
    assert [action for item in events for action in engine.process(item)] == [GestureAction.SPACE]


def test_two_finger_scroll_is_not_tap() -> None:
    engine = GestureEngine()
    events = [
        event(ContactPhase.DOWN, 1, 0.2, 0.2, 0),
        event(ContactPhase.DOWN, 2, 0.7, 0.2, 5),
        event(ContactPhase.MOVE, 1, 0.2, 0.4, 40),
        event(ContactPhase.UP, 1, 0.2, 0.4, 60),
        event(ContactPhase.UP, 2, 0.7, 0.4, 65),
    ]
    assert not [action for item in events for action in engine.process(item)]


def test_long_hold_is_not_tap() -> None:
    engine = GestureEngine()
    events = [
        event(ContactPhase.DOWN, 1, 0.2, 0.2, 0),
        event(ContactPhase.DOWN, 2, 0.7, 0.2, 5),
        event(ContactPhase.UP, 1, 0.2, 0.2, 300),
        event(ContactPhase.UP, 2, 0.7, 0.2, 310),
    ]
    assert not [action for item in events for action in engine.process(item)]


def test_brief_second_contact_without_overlap_is_not_tap() -> None:
    engine = GestureEngine(overlap_min_ms=25)
    events = [
        event(ContactPhase.DOWN, 1, 0.2, 0.2, 0),
        event(ContactPhase.DOWN, 2, 0.7, 0.2, 50),
        event(ContactPhase.UP, 2, 0.7, 0.2, 55),
        event(ContactPhase.UP, 1, 0.2, 0.2, 80),
    ]
    assert not [action for item in events for action in engine.process(item)]

