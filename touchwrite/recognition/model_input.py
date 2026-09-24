"""Geometry-preserving model-input preparation strategies."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass(frozen=True, slots=True)
class ModelInputStrategy:
    name: str = "processor_direct"
    canvas_size: int = 384
    target_occupancy: float | None = None
    target_height_fraction: float | None = None
    margin: int = 12
    foreground_threshold: int = 250

    def __post_init__(self) -> None:
        if self.name not in {
            "processor_direct",
            "full_letterbox",
            "letterbox_square",
            "ink_occupancy",
            "normalized_height",
        }:
            raise ValueError(f"unsupported model input strategy: {self.name}")
        if self.canvas_size < 1 or self.margin < 0 or self.margin * 2 >= self.canvas_size:
            raise ValueError("canvas size and margin must leave usable space")
        if self.target_occupancy is not None and not 0 < self.target_occupancy < 1:
            raise ValueError("target occupancy must be between zero and one")
        if self.name == "ink_occupancy" and self.target_occupancy is None:
            raise ValueError("ink_occupancy requires target_occupancy")
        if self.target_height_fraction is not None and not 0 < self.target_height_fraction < 1:
            raise ValueError("target height fraction must be between zero and one")
        if self.name == "normalized_height" and self.target_height_fraction is None:
            raise ValueError("normalized_height requires target_height_fraction")


def prepare_model_image(image: Image.Image, strategy: ModelInputStrategy) -> Image.Image:
    """Prepare an image without independently scaling its horizontal and vertical axes."""
    grayscale = image.convert("L")
    if strategy.name == "processor_direct":
        return grayscale
    if strategy.name == "full_letterbox":
        return _letterbox_full(grayscale, strategy.canvas_size, strategy.margin)
    if strategy.name == "letterbox_square":
        crop = _tight_crop(grayscale, strategy.foreground_threshold)
        return _letterbox_full(crop, strategy.canvas_size, strategy.margin)
    if strategy.name == "normalized_height":
        return _normalize_ink_height(
            grayscale,
            strategy.canvas_size,
            strategy.margin,
            strategy.target_height_fraction or 0.4,
            strategy.foreground_threshold,
        )
    return _letterbox_ink_for_occupancy(
        grayscale,
        strategy.canvas_size,
        strategy.margin,
        strategy.target_occupancy or 0.1,
        strategy.foreground_threshold,
    )


def _letterbox_full(image: Image.Image, size: int, margin: int) -> Image.Image:
    scale = min((size - 2 * margin) / image.width, (size - 2 * margin) / image.height)
    return _scaled_on_canvas(image, size, scale)


def _letterbox_ink_for_occupancy(
    image: Image.Image,
    size: int,
    margin: int,
    target_occupancy: float,
    threshold: int,
) -> Image.Image:
    grayscale = np.asarray(image)
    foreground = grayscale < threshold
    if not foreground.any():
        return Image.new("L", (size, size), 255)
    crop = _tight_crop(image, threshold)
    foreground_pixels = max(1, int(foreground.sum()))
    occupancy_scale = math.sqrt((target_occupancy * size * size) / foreground_pixels)
    fit_scale = min((size - 2 * margin) / crop.width, (size - 2 * margin) / crop.height)
    return _scaled_on_canvas(crop, size, min(occupancy_scale, fit_scale))


def _normalize_ink_height(
    image: Image.Image,
    size: int,
    margin: int,
    target_height_fraction: float,
    threshold: int,
) -> Image.Image:
    foreground = np.asarray(image) < threshold
    if not foreground.any():
        return Image.new("L", (size, size), 255)
    crop = _tight_crop(image, threshold)
    target_height = max(1, round(size * target_height_fraction))
    height_scale = target_height / crop.height
    fit_scale = min((size - 2 * margin) / crop.width, (size - 2 * margin) / crop.height)
    return _scaled_on_canvas(crop, size, min(height_scale, fit_scale))


def _tight_crop(image: Image.Image, threshold: int) -> Image.Image:
    positions = np.argwhere(np.asarray(image) < threshold)
    if not positions.size:
        return image.copy()
    min_y, min_x = positions.min(axis=0)
    max_y, max_x = positions.max(axis=0)
    return image.crop((int(min_x), int(min_y), int(max_x + 1), int(max_y + 1)))


def _scaled_on_canvas(image: Image.Image, size: int, scale: float) -> Image.Image:
    width = max(1, min(size, round(image.width * scale)))
    height = max(1, min(size, round(image.height * scale)))
    resized = image.resize((width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("L", (size, size), 255)
    canvas.paste(resized, ((size - width) // 2, (size - height) // 2))
    return canvas
