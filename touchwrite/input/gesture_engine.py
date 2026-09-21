"""Deterministic two-finger tap recognition independent of hardware."""

from __future__ import annotations

import math
from dataclasses import dataclass

from touchwrite.input.base import ContactEvent, ContactPhase, GestureAction


@dataclass(slots=True)
class _ContactTrack:
    started_ns: int
    start_x: float
    start_y: float
    last_x: float
    last_y: float
    ended_ns: int | None = None

    @property
    def travel(self) -> float:
        return math.hypot(self.last_x - self.start_x, self.last_y - self.start_y)


class GestureEngine:
    def __init__(
        self,
        tap_max_ms: int = 220,
        max_travel: float = 0.035,
        overlap_min_ms: int = 25,
    ) -> None:
        self.tap_max_ns = tap_max_ms * 1_000_000
        self.max_travel = max_travel
        self.overlap_min_ns = overlap_min_ms * 1_000_000
        self._tracks: dict[int, _ContactTrack] = {}
        self._candidate_ids: set[int] = set()

    def process(self, event: ContactEvent) -> list[GestureAction]:
        if event.phase is ContactPhase.DOWN:
            self._tracks[event.contact_id] = _ContactTrack(
                event.timestamp_ns, event.x, event.y, event.x, event.y
            )
            active = [key for key, track in self._tracks.items() if track.ended_ns is None]
            if len(active) == 2:
                self._candidate_ids = set(active)
            elif len(active) > 2:
                self._candidate_ids.clear()
            return []
        track = self._tracks.get(event.contact_id)
        if track is None:
            return []
        track.last_x, track.last_y = event.x, event.y
        if track.travel > self.max_travel:
            self._candidate_ids.discard(event.contact_id)
        if event.phase is not ContactPhase.UP:
            return []
        track.ended_ns = event.timestamp_ns
        if not self._candidate_ids or any(
            self._tracks[item].ended_ns is None for item in self._candidate_ids
        ):
            return []
        tracks = [self._tracks[item] for item in self._candidate_ids]
        duration = max(item.ended_ns or 0 for item in tracks) - min(
            item.started_ns for item in tracks
        )
        overlap = min(item.ended_ns or 0 for item in tracks) - max(
            item.started_ns for item in tracks
        )
        valid = (
            len(tracks) == 2
            and duration <= self.tap_max_ns
            and overlap >= self.overlap_min_ns
            and all(item.travel <= self.max_travel for item in tracks)
        )
        for item in self._candidate_ids:
            self._tracks.pop(item, None)
        self._candidate_ids.clear()
        return [GestureAction.SPACE] if valid else []

    def reset(self) -> None:
        self._tracks.clear()
        self._candidate_ids.clear()

