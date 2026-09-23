"""Recognition, rendering, and persistence orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

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
        debug_dir: Path | None = None,
    ) -> None:
        self.recognizer = recognizer
        self.renderer = renderer
        self.store = store
        self.smoother = smoother
        self.postprocessor = postprocessor or TextPostprocessor()
        self.debug_dir = debug_dir

    def commit(self, word: HandwrittenWord, terminator: str, context: str = "") -> CommitOutcome:
        return self._recognize(word, terminator, context, persist=True)

    def preview(self, word: HandwrittenWord, context: str = "") -> CommitOutcome:
        """Recognize through the authoritative pipeline without persisting the sample."""
        return self._recognize(word, "", context, persist=False)

    def commit_cached(
        self,
        word: HandwrittenWord,
        result: RecognitionResult,
        context: str = "",
    ) -> CommitOutcome:
        """Persist an exact-snapshot preview result without invoking the model again."""
        raw_image, processed_image = self._render_images(word)
        return self._finish(word, result, "", context, raw_image, processed_image, persist=True)

    def _recognize(
        self,
        word: HandwrittenWord,
        terminator: str,
        context: str,
        *,
        persist: bool,
    ) -> CommitOutcome:
        if not word.strokes or not any(stroke.points for stroke in word.strokes):
            raise ValueError("cannot recognize an empty word")
        raw_image, processed_image = self._render_images(word)
        result = self.recognizer.recognize(RecognitionSample(word, processed_image, context))
        return self._finish(
            word, result, terminator, context, raw_image, processed_image, persist=persist
        )

    def _render_images(self, word: HandwrittenWord) -> tuple[Image.Image, Image.Image]:
        if not word.strokes or not any(stroke.points for stroke in word.strokes):
            raise ValueError("cannot recognize an empty word")
        raw_image = self.renderer.render(word, filter_noise=False)
        processed_word = HandwrittenWord(
            strokes=self._processed_strokes(word.strokes),
            word_id=word.word_id,
            created_at=word.created_at,
        )
        rendered_image = self.renderer.render(processed_word, filter_noise=False)
        processed_image = self.renderer.render(processed_word, filter_noise=True)
        if self.debug_dir is not None:
            self._save_debug_artifacts(word, raw_image, rendered_image, processed_image)
        return raw_image, processed_image

    def _finish(
        self,
        word: HandwrittenWord,
        result: RecognitionResult,
        terminator: str,
        context: str,
        raw_image: Image.Image,
        processed_image: Image.Image,
        *,
        persist: bool,
    ) -> CommitOutcome:
        final_text = self.postprocessor.process(result.text, context)
        word.raw_prediction = result.raw_text or result.text
        word.predicted_text = final_text
        word.confidence = result.confidence
        word.model_name = result.model_name
        sample_id = None
        if persist and self.store is not None:
            self.store.save(word, raw_image, processed_image)
            sample_id = word.word_id
        return CommitOutcome(word, result, final_text + terminator, sample_id)

    def _save_debug_artifacts(
        self,
        word: HandwrittenWord,
        raw_image: Image.Image,
        rendered_image: Image.Image,
        processed_image: Image.Image,
    ) -> None:
        sample_dir = self.debug_dir / word.word_id
        sample_dir.mkdir(parents=True, exist_ok=True)
        raw_image.save(sample_dir / "raw_strokes.png")
        rendered_image.save(sample_dir / "rendered.png")
        processed_image.save(sample_dir / "processed.png")
        (sample_dir / "preprocessing.json").write_text(
            json.dumps(
                {
                    "word_id": word.word_id,
                    "render_width": self.renderer.width,
                    "render_height": self.renderer.height,
                    "padding": self.renderer.padding,
                    "stroke_width": self.renderer.stroke_width,
                    "supersample": self.renderer.supersample,
                    "noise_filter": self.renderer.filter_noise,
                    "smoothing": self.smoother is not None,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _processed_strokes(self, strokes: list[Stroke]) -> list[Stroke]:
        if self.smoother is None:
            return [Stroke(stroke.stroke_id, list(stroke.points)) for stroke in strokes]
        return [self.smoother.smooth(stroke) for stroke in strokes]
