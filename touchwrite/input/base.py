"""Platform-neutral contact event contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ContactPhase(StrEnum):
    DOWN = "down"
    MOVE = "move"
    UP = "up"


@dataclass(frozen=True, slots=True)
class ContactEvent:
    phase: ContactPhase
    contact_id: int
    x: float
    y: float
    timestamp_ns: int


class GestureAction(StrEnum):
    SPACE = "space"
