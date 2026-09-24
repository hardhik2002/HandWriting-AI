from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from touchwrite.diagnostics.accuracy import image_metrics
from touchwrite.recognition.model_input import ModelInputStrategy, prepare_model_image


def word_image() -> Image.Image:
    image = Image.new("L", (512, 128), 255)
    ImageDraw.Draw(image).rectangle((100, 40, 399, 89), fill=0)
    return image


def test_full_letterbox_preserves_foreground_aspect_ratio() -> None:
    source = image_metrics(word_image())
    prepared = image_metrics(
        prepare_model_image(word_image(), ModelInputStrategy("full_letterbox"))
    )
    assert prepared.dimensions == (384, 384)
    assert prepared.aspect_ratio is not None
    assert source.aspect_ratio is not None
    assert abs(prepared.aspect_ratio - source.aspect_ratio) < 0.15


def test_occupancy_normalization_is_monotonic_and_aspect_preserving() -> None:
    low = image_metrics(
        prepare_model_image(
            word_image(), ModelInputStrategy("ink_occupancy", target_occupancy=0.05)
        )
    )
    high = image_metrics(
        prepare_model_image(
            word_image(), ModelInputStrategy("ink_occupancy", target_occupancy=0.15)
        )
    )
    assert high.occupancy_percent > low.occupancy_percent
    assert low.aspect_ratio is not None and high.aspect_ratio is not None
    assert abs(low.aspect_ratio - high.aspect_ratio) < 0.1


def test_processor_direct_preserves_existing_baseline_object_geometry() -> None:
    source = word_image()
    prepared = prepare_model_image(source, ModelInputStrategy())
    assert prepared.size == source.size
    assert prepared.tobytes() == source.tobytes()


def test_tight_letterbox_preserves_ink_aspect_ratio() -> None:
    source = image_metrics(word_image())
    prepared = image_metrics(
        prepare_model_image(word_image(), ModelInputStrategy("letterbox_square"))
    )

    assert prepared.dimensions == (384, 384)
    assert prepared.aspect_ratio == pytest.approx(source.aspect_ratio, rel=0.03)


def test_normalized_height_targets_fraction_without_stretching() -> None:
    image = Image.new("L", (512, 128), 255)
    ImageDraw.Draw(image).rectangle((100, 40, 179, 79), fill=0)
    source = image_metrics(image)
    prepared = image_metrics(
        prepare_model_image(
            image,
            ModelInputStrategy("normalized_height", target_height_fraction=0.4),
        )
    )

    assert prepared.foreground_height == pytest.approx(384 * 0.4, abs=2)
    assert prepared.aspect_ratio == pytest.approx(source.aspect_ratio, rel=0.03)
