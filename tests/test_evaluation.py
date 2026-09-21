from __future__ import annotations

import json

import pytest

from touchwrite.tools.evaluate import calculate_metrics, edit_distance
from touchwrite.tools.export_dataset import export_dataset


def test_edit_distance_and_metrics() -> None:
    assert edit_distance("hello", "hallo") == 1
    metrics = calculate_metrics([("hello", "hello", 10.0), ("world", "word", 20.0)])
    assert metrics.exact_word_accuracy == 0.5
    assert metrics.character_error_rate == pytest.approx(0.1)
    assert metrics.average_inference_latency_ms == 15.0


def test_export_only_includes_corrected_samples(tmp_path) -> None:
    labeled = tmp_path / "data" / "one"
    unlabeled = tmp_path / "data" / "two"
    labeled.mkdir(parents=True)
    unlabeled.mkdir(parents=True)
    (labeled / "metadata.json").write_text(
        json.dumps({"word_id": "one", "corrected_text": "hello", "prediction": "helo"})
    )
    (unlabeled / "metadata.json").write_text(
        json.dumps({"word_id": "two", "corrected_text": None, "prediction": "test"})
    )
    output = tmp_path / "dataset.jsonl"
    assert export_dataset(tmp_path / "data", output) == 1
    assert json.loads(output.read_text())["label"] == "hello"

