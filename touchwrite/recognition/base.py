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


class RecognitionError(RuntimeError):
    """A recoverable recognition failure."""


class HandwritingRecognizer(ABC):
    @abstractmethod
    def recognize(self, sample: RecognitionSample) -> RecognitionResult:
        """Recognize a single word image without mutating application state."""

