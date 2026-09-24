"""Recognition contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from PIL import Image

from touchwrite.ink.models import HandwrittenWord


@dataclass(frozen=True, slots=True)
class RecognitionCandidate:
    text: str
    score: float | None = None


@dataclass(frozen=True, slots=True)
class RecognitionSample:
    word: HandwrittenWord
    image: Image.Image
    context: str = ""


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    text: str
    model_name: str
    inference_duration_ms: float
    confidence: float | None = None
    alternatives: tuple[RecognitionCandidate, ...] = field(default_factory=tuple)
    raw_text: str | None = None
    model_load_duration_ms: float | None = None
    processing_duration_ms: float | None = None
    generation_duration_ms: float | None = None
    decoding_duration_ms: float | None = None
    device: str | None = None
    processor_mode: str | None = None
    generation_settings: dict[str, object] = field(default_factory=dict)
    sequence_score: float | None = None


class RecognitionError(RuntimeError):
    """A recoverable recognition failure."""


class HandwritingRecognizer(ABC):
    @abstractmethod
    def recognize(self, sample: RecognitionSample) -> RecognitionResult:
        """Recognize a single word image without mutating application state."""
