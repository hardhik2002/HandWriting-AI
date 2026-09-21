"""Explicit future boundary for a trajectory-native model."""

from __future__ import annotations

from touchwrite.recognition.base import (
    HandwritingRecognizer,
    RecognitionError,
    RecognitionResult,
    RecognitionSample,
)


class OnlineHandwritingRecognizer(HandwritingRecognizer):
    def recognize(self, sample: RecognitionSample) -> RecognitionResult:
        raise RecognitionError(
            "online recognizer is not trained; image recognition remains the validated fallback"
        )

