"""Strongly typed online-handwriting domain models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float
    timestamp_ns: int
    x_raw: float
    y_raw: float
    pressure: float | None = None
    contact_id: int | None = None
    finger_down: bool = True
    dx: float = 0.0
    dy: float = 0.0
    velocity: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.x <= 1.0 or not 0.0 <= self.y <= 1.0:
            raise ValueError("normalized point coordinates must be in [0, 1]")
        if self.timestamp_ns < 0:
            raise ValueError("timestamp_ns must not be negative")


@dataclass(slots=True)
class Stroke:
    stroke_id: int
    points: list[Point] = field(default_factory=list)

    @property
    def start_time_ns(self) -> int | None:
        return self.points[0].timestamp_ns if self.points else None

    @property
    def end_time_ns(self) -> int | None:
        return self.points[-1].timestamp_ns if self.points else None


@dataclass(slots=True)
class HandwrittenWord:
    strokes: list[Stroke]
    word_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    rendered_image_path: str | None = None
    expected_text: str | None = None
    predicted_text: str | None = None
    raw_prediction: str | None = None
    confidence: float | None = None
    model_name: str | None = None
    document_id: str | None = None
    line_index: int | None = None
    word_index: int | None = None
    commit_sequence_id: int | None = None
    recognition_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> HandwrittenWord:
        strokes = [
            Stroke(
                stroke_id=int(stroke["stroke_id"]),
                points=[Point(**point) for point in stroke.get("points", [])],
            )
            for stroke in value.get("strokes", [])
        ]
        known = {
            key: item
            for key, item in value.items()
            if key in cls.__dataclass_fields__ and key != "strokes"
        }
        return cls(strokes=strokes, **known)
