from __future__ import annotations

from touchwrite.recognition.image_recognizer import (
    ImageHandwritingRecognizer,
    is_single_word_candidate,
    select_single_word_candidate,
)


def test_single_word_candidate_allows_internal_apostrophe_and_hyphen() -> None:
    assert is_single_word_candidate("can't")
    assert is_single_word_candidate("touch-write")
    assert not is_single_word_candidate("two words")
    assert not is_single_word_candidate("word.")


def test_candidate_selection_uses_model_beam_without_rewriting_characters() -> None:
    candidates = ("hardhi K", "hardhik", "hardhi k")
    assert select_single_word_candidate(candidates) == "hardhik"


def test_recognizer_defaults_are_explicit_and_deterministic() -> None:
    recognizer = ImageHandwritingRecognizer("test/model")
    assert recognizer.processor_use_fast is False
    assert recognizer.beam_width == 8
    assert recognizer.max_new_tokens == 24
