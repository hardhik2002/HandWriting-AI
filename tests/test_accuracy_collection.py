from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

from tests.helpers import stroke
from touchwrite.collection.accuracy import (
    DIFFICULT_REPETITIONS,
    DIFFICULT_WORDS,
    build_accuracy_prompts,
    create_accuracy_session,
    edit_operations,
    evaluate_accuracy_manifest,
    load_accuracy_session,
    record_accuracy_sample,
)
from touchwrite.ink.models import HandwrittenWord
from touchwrite.recognition.base import RecognitionCandidate, RecognitionResult
from touchwrite.tools.benchmark_preprocessing import BASELINE_VARIANT, VARIANTS


def test_accuracy_prompt_queue_has_required_repetitions() -> None:
    prompts = build_accuracy_prompts("stable-session")
    counts = Counter(prompt["expected"] for prompt in prompts)

    assert 100 <= len(prompts) <= 130
    assert all(counts[word] == DIFFICULT_REPETITIONS for word in DIFFICULT_WORDS)
    assert {"python", "engineer", "windows", "1", "l"} <= set(counts)
    assert [prompt["prompt_id"] for prompt in prompts] == [
        f"p{index:03d}" for index in range(1, len(prompts) + 1)
    ]


def test_preprocessing_grid_uses_current_baseline_and_bounded_experiments() -> None:
    names = {variant.name for variant in VARIANTS}

    assert BASELINE_VARIANT.stroke_width == 6
    assert {"letterbox_square", "height_20", "height_70", "resample_2"} <= names
    assert {"stroke_3", "stroke_12", "supersample_4", "occupancy_10"} <= names
    assert len(VARIANTS) <= 24


def test_edit_operations_reports_insertions_deletions_and_substitutions() -> None:
    assert edit_operations(list("hi"), list("his")) == [("insertion", None, "s")]
    assert edit_operations(list("hi"), list("h")) == [("deletion", "i", None)]
    assert edit_operations(list("hi"), list("ho")) == [("substitution", "i", "o")]


def test_record_accuracy_sample_preserves_ground_truth_and_artifacts(tmp_path: Path) -> None:
    session = create_accuracy_session(
        tmp_path / "accuracy", session_id="session-one"
    )
    manifest = load_accuracy_session(session)
    prompt = manifest["prompts"][0]
    word = HandwrittenWord([stroke()], expected_text=prompt["expected"])
    sample_dir = session / "samples" / word.word_id
    sample_dir.mkdir()
    Image.new("RGB", (384, 384), "white").save(sample_dir / "model_input.png")
    (sample_dir / "model_input.json").write_text(
        json.dumps({"tensor_mean": 0.9, "tensor_standard_deviation": 0.1}),
        encoding="utf-8",
    )
    (sample_dir / "preprocessing.json").write_text(
        json.dumps({"stroke_width": 6}), encoding="utf-8"
    )
    processed = Image.new("L", (512, 128), 255)
    draw = ImageDraw.Draw(processed)
    draw.line((20, 64, 200, 64), fill=0, width=6)
    result = RecognitionResult(
        text="wrong",
        raw_text="wrong",
        model_name="test-model",
        inference_duration_ms=12.5,
        alternatives=(RecognitionCandidate("other", -1.2),),
        sequence_score=-0.8,
    )

    record = record_accuracy_sample(
        session,
        prompt["prompt_id"],
        word,
        processed,
        processed,
        result,
    )
    updated = load_accuracy_session(session)

    assert record["expected"] == prompt["expected"]
    assert record["prediction"] == "wrong"
    assert record["preprocessing"]["stroke_width"] == 6
    assert record["processor_tensor_statistics"]["tensor_mean"] == 0.9
    assert updated["prompts"][0]["status"] == "completed"
    assert (session / record["artifacts"]["trajectory"]).is_file()
    assert (session / record["artifacts"]["cropped_image"]).is_file()
    assert (session / "index.html").is_file()


def test_baseline_metrics_are_computed_from_displayed_labels() -> None:
    manifest = {
        "session_id": "one",
        "prompts": [{}, {}],
        "samples": [
            {
                "prompt_id": "p1",
                "sample_id": "s1",
                "expected": "hi",
                "prediction": "his",
                "exact": False,
                "result": {"latency_ms": 10.0},
            },
            {
                "prompt_id": "p2",
                "sample_id": "s2",
                "expected": "I",
                "prediction": "I",
                "exact": True,
                "result": {"latency_ms": 20.0},
            },
        ],
    }

    report = evaluate_accuracy_manifest(manifest)

    assert report["exact_accuracy"] == 0.5
    assert report["cer"] == 1 / 3
    assert report["insertions"] == 1
    assert report["deletions"] == 0
    assert report["substitutions"] == 0
    assert report["short_word_accuracy"] == 0.5
