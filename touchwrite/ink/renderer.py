"""Aspect-preserving handwriting rasterization for UI/model input."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from touchwrite.ink.models import HandwrittenWord, Point, Stroke


@dataclass(frozen=True, slots=True)
class InkBoundingBox:
    min_x: float
    min_y: float
    max_x: float
    max_y: float


def _coordinates(point: Point) -> tuple[float, float]:
    """Return undistorted window coordinates retained by the capture provider."""
    return point.x_raw, point.y_raw


def stroke_path_length(stroke: Stroke) -> float:
    points = stroke.points
    return sum(
        ((_coordinates(points[index])[0] - _coordinates(points[index - 1])[0]) ** 2
        + (_coordinates(points[index])[1] - _coordinates(points[index - 1])[1]) ** 2)
        ** 0.5
        for index in range(1, len(points))
    )


def filter_isolated_point_strokes(strokes: list[Stroke]) -> list[Stroke]:
    """Omit remote click noise while preserving dots close to substantive handwriting.

    The raw trajectories remain untouched. A zero-length stroke near the main ink is retained so
    dots over ``i`` and ``j`` continue to render. Only point strokes spatially isolated from every
    substantive stroke are excluded from model images.
    """
    substantive = [stroke for stroke in strokes if stroke_path_length(stroke) >= 1.0]
    if not substantive:
        return list(strokes)
    substantive_points = [point for stroke in substantive for point in stroke.points]
    y_values = [_coordinates(point)[1] for point in substantive_points]
    ink_height = max(y_values) - min(y_values)
    maximum_distance = max(16.0, ink_height * 0.5)
    output: list[Stroke] = []
    for stroke in strokes:
        if stroke_path_length(stroke) >= 1.0 or not stroke.points:
            output.append(stroke)
            continue
        x, y = _coordinates(stroke.points[0])
        nearest = min(
            ((x - _coordinates(point)[0]) ** 2 + (y - _coordinates(point)[1]) ** 2) ** 0.5
            for point in substantive_points
        )
        if nearest <= maximum_distance:
            output.append(stroke)
    return output


def bounding_box(strokes: list[Stroke]) -> InkBoundingBox | None:
    points = [point for stroke in strokes for point in stroke.points]
    if not points:
        return None
    coordinates = [_coordinates(point) for point in points]
    return InkBoundingBox(
        min(point[0] for point in coordinates),
        min(point[1] for point in coordinates),
        max(point[0] for point in coordinates),
        max(point[1] for point in coordinates),
    )


class InkRenderer:
    def __init__(
        self,
        width: int = 512,
        height: int = 128,
        padding: int = 16,
        stroke_width: int = 8,
        supersample: int = 3,
        filter_noise: bool = True,
    ) -> None:
        self.width = width
        self.height = height
        self.padding = padding
        self.stroke_width = stroke_width
        self.supersample = supersample
        self.filter_noise = filter_noise

    def render(
        self, word: HandwrittenWord, *, filter_noise: bool | None = None
    ) -> Image.Image:
        scale = self.supersample
        image = Image.new("L", (self.width * scale, self.height * scale), 255)
        should_filter = self.filter_noise if filter_noise is None else filter_noise
        strokes = filter_isolated_point_strokes(word.strokes) if should_filter else word.strokes
        bounds = bounding_box(strokes)
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
        for stroke in strokes:
            positions = [transform(*_coordinates(point)) for point in stroke.points]
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
