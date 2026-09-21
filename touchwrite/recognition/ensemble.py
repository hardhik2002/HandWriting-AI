"""Candidate fusion boundary for future measured ensembles."""

from __future__ import annotations

from touchwrite.recognition.base import HandwritingRecognizer, RecognitionResult, RecognitionSample


class EnsembleRecognizer(HandwritingRecognizer):
    """Run a configured primary model without inventing unvalidated fusion weights."""

    def __init__(self, primary: HandwritingRecognizer) -> None:
        self.primary = primary

    def recognize(self, sample: RecognitionSample) -> RecognitionResult:
        return self.primary.recognize(sample)

