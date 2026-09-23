from __future__ import annotations

from PIL import Image

from touchwrite.diagnostics.accuracy import (
    character_error_count,
    compare_images,
    image_metrics,
    trajectory_metrics,
)
from touchwrite.ink.models import HandwrittenWord, Point, Stroke


def test_image_metrics_report_bbox_padding_and_occupancy() -> None:
    image = Image.new("L", (10, 8), 255)
    for y in range(2, 6):
        for x in range(3, 8):
            image.putpixel((x, y), 0)
    metrics = image_metrics(image)
    assert metrics.foreground_bbox == (3, 2, 8, 6)
    assert metrics.padding == (3, 2, 2, 2)
    assert metrics.occupancy_percent == 25.0


def test_pixel_comparison_is_exact_not_visual() -> None:
    left = Image.new("L", (4, 4), 255)
    right = left.copy()
    assert compare_images(left, right)["pixel_identical"]
    right.putpixel((1, 1), 254)
    comparison = compare_images(left, right)
    assert not comparison["pixel_identical"]
    assert comparison["different_pixels"] == 1


def test_trajectory_metrics_keep_detached_dot_and_terminal_strokes() -> None:
    body = Stroke(
        1,
        [Point(0.1, 0.2, 1, 10, 30), Point(0.8, 0.8, 2_000_001, 80, 90)],
    )
    dot = Stroke(
        2,
        [Point(0.5, 0.1, 3_000_001, 15, 10), Point(0.5, 0.1, 4_000_001, 15, 10)],
    )
    metrics = trajectory_metrics(HandwrittenWord([body, dot]))
    assert metrics["stroke_count"] == 2
    assert metrics["point_count"] == 4
    assert metrics["filtered_stroke_ids"] == []
    assert metrics["terminal_strokes"][-1]["retained_by_noise_filter"]


def test_character_error_count() -> None:
    assert character_error_count("hardhik", "hardhijk") == 1
    assert character_error_count("hi", "32h.i") == 3
