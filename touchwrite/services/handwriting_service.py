"""Recognition, rendering, and persistence orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from touchwrite.ink.models import HandwrittenWord, Stroke
from touchwrite.ink.renderer import InkRenderer
from touchwrite.ink.smoother import MovingAverageSmoother
from touchwrite.persistence.session_store import SessionStore
from touchwrite.recognition.base import HandwritingRecognizer, RecognitionResult, RecognitionSample
from touchwrite.recognition.postprocessor import TextPostprocessor


@dataclass(frozen=True, slots=True)
class CommitOutcome:
    word: HandwrittenWord
    result: RecognitionResult
    inserted_text: str
    sample_id: str | None


class HandwritingService:
    def __init__(
        self,
        recognizer: HandwritingRecognizer,
        renderer: InkRenderer,
        store: SessionStore | None,
        smoother: MovingAverageSmoother | None = None,
        postprocessor: TextPostprocessor | None = None,
    ) -> None:
        self.recognizer = recognizer
        self.renderer = renderer
        self.store = store
        self.smoother = smoother
        self.postprocessor = postprocessor or TextPostprocessor()

    def commit(self, word: HandwrittenWord, terminator: str, context: str = "") -> CommitOutcome:
        if not word.strokes or not any(stroke.points for stroke in word.strokes):
            raise ValueError("cannot recognize an empty word")
        raw_image = self.renderer.render(word)
        processed_word = HandwrittenWord(
            strokes=self._processed_strokes(word.strokes),
            word_id=word.word_id,
            created_at=word.created_at,
        )
        processed_image = self.renderer.render(processed_word)
        result = self.recognizer.recognize(RecognitionSample(word, processed_image, context))
        final_text = self.postprocessor.process(result.text, context)
        word.raw_prediction = result.raw_text or result.text
        word.predicted_text = final_text
        word.confidence = result.confidence
        word.model_name = result.model_name
        sample_id = None
        if self.store is not None:
            self.store.save(word, raw_image, processed_image)
            sample_id = word.word_id
        return CommitOutcome(word, result, final_text + terminator, sample_id)

    def _processed_strokes(self, strokes: list[Stroke]) -> list[Stroke]:
        if self.smoother is None:
            return [Stroke(stroke.stroke_id, list(stroke.points)) for stroke in strokes]
        return [self.smoother.smooth(stroke) for stroke in strokes]

