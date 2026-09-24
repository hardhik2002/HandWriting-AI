from __future__ import annotations

import json
from pathlib import Path

from PIL import ImageChops

from touchwrite.config.settings import Settings
from touchwrite.tools.benchmark_preprocessing import (
    VARIANTS,
    load_evaluation_items,
    render_variant,
)


def test_accuracy_manifests_have_explicit_labels_and_existing_samples() -> None:
    historical = Path("tests/fixtures/historical_accuracy.json")
    touchscreen = Path("tests/fixtures/touchscreen_accuracy.json")
    for path in (historical, touchscreen):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert manifest["samples"]
        for sample in manifest["samples"]:
            assert sample["expected"].strip()
            assert sample["verification"].strip()
            assert (Path("data/handwriting") / sample["sample_id"] / "trajectory.json").is_file()


def test_preprocessing_variant_is_reproducible() -> None:
    items = load_evaluation_items(
        Path("tests/fixtures/historical_accuracy.json"),
        Path("tests/fixtures/touchscreen_accuracy.json"),
        Path("data/handwriting"),
    )
    first = render_variant(items[0]["word"], Settings(), VARIANTS[0])
    second = render_variant(items[0]["word"], Settings(), VARIANTS[0])
    assert ImageChops.difference(first, second).getbbox() is None

