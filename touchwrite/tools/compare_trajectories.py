"""Generate point/direction and raster comparisons for two labeled trajectories."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from touchwrite.config.settings import Settings
from touchwrite.diagnostics.accuracy import image_metrics, load_sample, trajectory_metrics
from touchwrite.ink.models import HandwrittenWord, Stroke
from touchwrite.ink.renderer import InkRenderer, bounding_box
from touchwrite.ink.smoother import MovingAverageSmoother

COLORS = ("#2563eb", "#dc2626", "#059669", "#7c3aed", "#d97706", "#0891b2")


def trajectory_panel(strokes: list[Stroke], size: tuple[int, int]) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    bounds = bounding_box(strokes)
    if bounds is None:
        return image
    margin = 20
    width = max(bounds.max_x - bounds.min_x, 1.0)
    height = max(bounds.max_y - bounds.min_y, 1.0)
    scale = min((size[0] - 2 * margin) / width, (size[1] - 2 * margin) / height)

    def transform(x: float, y: float) -> tuple[float, float]:
        return margin + (x - bounds.min_x) * scale, margin + (y - bounds.min_y) * scale

    for index, stroke in enumerate(strokes):
        color = COLORS[index % len(COLORS)]
        positions = [transform(point.x_raw, point.y_raw) for point in stroke.points]
        if len(positions) > 1:
            draw.line(positions, fill=color, width=2)
        for position in positions:
            draw.ellipse(
                (position[0] - 1.5, position[1] - 1.5, position[0] + 1.5, position[1] + 1.5),
                fill=color,
            )
        if len(positions) > 1:
            _draw_arrow(draw, positions[-2], positions[-1], color)
    return image


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    color: str,
) -> None:
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 7.0
    for offset in (-0.6, 0.6):
        point = (
            end[0] - math.cos(angle + offset) * length,
            end[1] - math.sin(angle + offset) * length,
        )
        draw.line((end, point), fill=color, width=2)


def create_comparison(
    historical_dir: Path,
    touchscreen_dir: Path,
    output_dir: Path,
) -> dict[str, object]:
    settings = Settings.from_environment()
    renderer = InkRenderer(
        settings.render_width,
        settings.render_height,
        settings.render_padding,
        settings.stroke_width,
    )
    smoother = MovingAverageSmoother(settings.smoothing_window)
    rows = []
    payload: dict[str, object] = {}
    for label, sample_dir in (
        ("Historical hardhik", historical_dir),
        ("Touchscreen hardhik", touchscreen_dir),
    ):
        word, metadata = load_sample(sample_dir)
        smoothed = [smoother.smooth(stroke) for stroke in word.strokes]
        processed = renderer.render(HandwrittenWord(smoothed), filter_noise=True)
        model_input = processed.resize((384, 384), Image.Resampling.BILINEAR)
        panels = [
            trajectory_panel(word.strokes, (380, 260)),
            trajectory_panel(smoothed, (380, 260)),
            processed.convert("RGB").resize((380, 95), Image.Resampling.LANCZOS),
            model_input.convert("RGB").resize((260, 260), Image.Resampling.LANCZOS),
        ]
        processed_metrics = image_metrics(processed)
        model_metrics = image_metrics(model_input)
        payload[label] = {
            "sample_id": word.word_id,
            "expected": "hardhik",
            "prediction": metadata.get("prediction"),
            "trajectory": trajectory_metrics(word),
            "processed": asdict(processed_metrics),
            "model_input": asdict(model_metrics),
        }
        rows.append((label, panels))

    canvas = Image.new("RGB", (1440, 660), "#f8fafc")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    headings = ("Raw trajectory + direction", "Smoothed trajectory", "Processed", "384x384 input")
    x_positions = (20, 420, 820, 1160)
    for x, heading in zip(x_positions, headings, strict=True):
        draw.text((x, 12), heading, fill="#111827", font=font)
    for row_index, (label, panels) in enumerate(rows):
        y = 45 + row_index * 300
        draw.text((20, y), label, fill="#111827", font=font)
        canvas.paste(panels[0], (20, y + 20))
        canvas.paste(panels[1], (420, y + 20))
        canvas.paste(panels[2], (820, y + 100))
        canvas.paste(panels[3], (1160, y + 20))
    output_dir.mkdir(parents=True, exist_ok=True)
    canvas.save(output_dir / "hardhik_comparison.png")
    (output_dir / "hardhik_comparison.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--historical",
        type=Path,
        default=Path("data/handwriting/ba216970-66de-4d3e-b192-7669dd273b86"),
    )
    parser.add_argument(
        "--touchscreen",
        type=Path,
        default=Path("data/handwriting/98ae9fd3-cb6c-4533-84f2-6a9fd66f5a8a"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("reports/trajectory_comparison")
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = create_comparison(args.historical, args.touchscreen, args.output)
    print(json.dumps({"samples": list(payload), "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
