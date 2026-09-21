"""Aspect-preserving handwriting rasterization for UI/model input."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from touchwrite.ink.models import HandwrittenWord, Stroke


@dataclass(frozen=True, slots=True)
class InkBoundingBox:
    min_x: float
    min_y: float
    max_x: float
    max_y: float


def bounding_box(strokes: list[Stroke]) -> InkBoundingBox | None:
    points = [point for stroke in strokes for point in stroke.points]
    if not points:
        return None
    return InkBoundingBox(
        min(point.x for point in points),
        min(point.y for point in points),
        max(point.x for point in points),
        max(point.y for point in points),
    )


class InkRenderer:
    def __init__(
        self,
        width: int = 512,
        height: int = 192,
        padding: int = 24,
        stroke_width: int = 8,
        supersample: int = 3,
    ) -> None:
        self.width = width
        self.height = height
        self.padding = padding
        self.stroke_width = stroke_width
        self.supersample = supersample

    def render(self, word: HandwrittenWord) -> Image.Image:
        scale = self.supersample
        image = Image.new("L", (self.width * scale, self.height * scale), 255)
        bounds = bounding_box(word.strokes)
        if bounds is None:
            return image.resize((self.width, self.height), Image.Resampling.LANCZOS)
        usable_width = max(1, (self.width - 2 * self.padding) * scale)
        usable_height = max(1, (self.height - 2 * self.padding) * scale)
        ink_width = max(bounds.max_x - bounds.min_x, 1e-6)
        ink_height = max(bounds.max_y - bounds.min_y, 1e-6)
        fit = min(usable_width / ink_width, usable_height / ink_height)
        offset_x = (image.width - ink_width * fit) / 2
        offset_y = (image.height - ink_height * fit) / 2

        def transform(x: float, y: float) -> tuple[float, float]:
            return offset_x + (x - bounds.min_x) * fit, offset_y + (y - bounds.min_y) * fit

        draw = ImageDraw.Draw(image)
        width = self.stroke_width * scale
        for stroke in word.strokes:
            positions = [transform(point.x, point.y) for point in stroke.points]
            if len(positions) == 1:
                x, y = positions[0]
                radius = width / 2
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=0)
            elif positions:
                draw.line(positions, fill=0, width=width, joint="curve")
                radius = width / 2
                for x, y in (positions[0], positions[-1]):
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=0)
        return image.resize((self.width, self.height), Image.Resampling.LANCZOS)

