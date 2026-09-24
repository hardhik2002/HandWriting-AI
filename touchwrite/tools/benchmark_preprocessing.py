"""Benchmark a bounded preprocessing grid on historical and touchscreen manifests."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from touchwrite.config.settings import Settings
from touchwrite.diagnostics.accuracy import (
    character_error_count,
    image_metrics,
    load_sample,
)
from touchwrite.ink.models import HandwrittenWord
from touchwrite.ink.renderer import InkRenderer
from touchwrite.ink.resampler import resample_strokes
from touchwrite.ink.smoother import MovingAverageSmoother
from touchwrite.recognition.base import RecognitionSample
from touchwrite.recognition.image_recognizer import ImageHandwritingRecognizer
from touchwrite.recognition.model_input import ModelInputStrategy, prepare_model_image


@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    strategy: ModelInputStrategy = ModelInputStrategy()
    stroke_width: int = 6
    smoothing_window: int | None = 3
    resample_spacing: float | None = None
    supersample: int = 3


BASELINE_VARIANT = Variant("baseline")
VARIANTS = (
    BASELINE_VARIANT,
    Variant("stroke_3", stroke_width=3),
    Variant("stroke_4", stroke_width=4),
    Variant("stroke_5", stroke_width=5),
    Variant("stroke_7", stroke_width=7),
    Variant("stroke_8", stroke_width=8),
    Variant("stroke_10", stroke_width=10),
    Variant("stroke_12", stroke_width=12),
    Variant("letterbox_square", ModelInputStrategy("letterbox_square")),
    *(
        Variant(
            f"height_{percent}",
            ModelInputStrategy(
                "normalized_height", target_height_fraction=percent / 100
            ),
        )
        for percent in (20, 30, 40, 50, 60, 70)
    ),
    Variant("occupancy_05", ModelInputStrategy("ink_occupancy", target_occupancy=0.05)),
    Variant("occupancy_10", ModelInputStrategy("ink_occupancy", target_occupancy=0.10)),
    Variant("occupancy_20", ModelInputStrategy("ink_occupancy", target_occupancy=0.20)),
    Variant("resample_2", resample_spacing=2.0),
    Variant("supersample_4", supersample=4),
)


def load_evaluation_items(
    historical_manifest: Path,
    touchscreen_manifest: Path,
    data_dir: Path,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for domain, manifest_path in (
        ("historical", historical_manifest),
        ("touchscreen", touchscreen_manifest),
    ):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest["samples"]:
            word, metadata = load_sample(data_dir / entry["sample_id"])
            items.append(
                {
                    "key": entry["sample_id"],
                    "sample_id": entry["sample_id"],
                    "domain": domain,
                    "level": entry.get("level", "word"),
                    "expected": entry["expected"],
                    "live_prediction": metadata.get("prediction"),
                    "word": word,
                }
            )
            for index, segment in enumerate(entry.get("segments", []), start=1):
                stroke_ids = set(segment["stroke_ids"])
                segment_word = HandwrittenWord(
                    [deepcopy(stroke) for stroke in word.strokes if stroke.stroke_id in stroke_ids],
                    recognition_metadata={
                        "source_word_id": word.word_id,
                        "source_stroke_ids": sorted(stroke_ids),
                    },
                )
                items.append(
                    {
                        "key": f"{entry['sample_id']}:segment:{index}",
                        "sample_id": entry["sample_id"],
                        "domain": "touchscreen-segment",
                        "level": "word",
                        "expected": segment["expected"],
                        "live_prediction": None,
                        "word": segment_word,
                    }
                )
    return items


def load_accuracy_session_items(session_dir: Path) -> list[dict[str, Any]]:
    manifest = json.loads((session_dir / "manifest.json").read_text(encoding="utf-8"))
    items = []
    for record in manifest.get("samples", []):
        trajectory_path = session_dir / record["artifacts"]["trajectory"]
        word = HandwrittenWord.from_dict(
            json.loads(trajectory_path.read_text(encoding="utf-8"))
        )
        items.append(
            {
                "key": record["prompt_id"],
                "sample_id": record["sample_id"],
                "domain": "touchscreen",
                "level": "word",
                "expected": record["expected"],
                "live_prediction": record["prediction"],
                "word": word,
            }
        )
    return items


def render_variant(word: HandwrittenWord, settings: Settings, variant: Variant) -> Image.Image:
    strokes = deepcopy(word.strokes)
    if variant.resample_spacing is not None:
        strokes = resample_strokes(strokes, variant.resample_spacing)
    if variant.smoothing_window is not None:
        smoother = MovingAverageSmoother(variant.smoothing_window)
        strokes = [smoother.smooth(stroke) for stroke in strokes]
    renderer = InkRenderer(
        settings.render_width,
        settings.render_height,
        settings.render_padding,
        variant.stroke_width,
        variant.supersample,
    )
    processed = renderer.render(HandwrittenWord(strokes), filter_noise=True)
    return prepare_model_image(processed, variant.strategy)


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize(records: list[dict[str, Any]], domain: str) -> dict[str, Any]:
    selected = [record for record in records if record["domain"] == domain]
    short = [record for record in selected if len(record["expected"]) <= 2]
    errors = sum(record["character_errors"] for record in selected)
    characters = sum(len(record["expected"]) for record in selected)
    latencies = [record["latency_ms"] for record in selected]
    return {
        "samples": len(selected),
        "exact_accuracy": (
            sum(record["exact"] for record in selected) / len(selected) if selected else None
        ),
        "cer": errors / characters if characters else None,
        "short_word_samples": len(short),
        "short_word_accuracy": (
            sum(record["exact"] for record in short) / len(short) if short else None
        ),
        "median_latency_ms": statistics.median(latencies) if latencies else None,
        "p95_latency_ms": percentile(latencies, 0.95) if latencies else None,
    }


def benchmark(
    items: list[dict[str, Any]],
    settings: Settings,
    variants: tuple[Variant, ...] = VARIANTS,
) -> dict[str, Any]:
    recognizer = ImageHandwritingRecognizer(
        settings.model_name,
        settings.model_device,
        settings.beam_width,
        settings.max_new_tokens,
        settings.processor_use_fast,
    )
    results = []
    benchmark_started = time.perf_counter()
    for variant in variants:
        print(f"benchmarking {variant.name} ({len(items)} samples)", flush=True)
        records = []
        for item in items:
            model_source = render_variant(item["word"], settings, variant)
            started = time.perf_counter()
            outcome = recognizer.recognize(
                RecognitionSample(item["word"], model_source, "")
            )
            latency_ms = (time.perf_counter() - started) * 1000
            prediction = outcome.text.strip()
            expected = item["expected"]
            simulated_model_input = model_source.resize(
                (384, 384), Image.Resampling.BILINEAR
            )
            records.append(
                {
                    "key": item["key"],
                    "sample_id": item["sample_id"],
                    "domain": item["domain"],
                    "level": item["level"],
                    "expected": expected,
                    "live_prediction": item["live_prediction"],
                    "prediction": prediction,
                    "exact": prediction == expected,
                    "character_errors": character_error_count(expected, prediction),
                    "latency_ms": latency_ms,
                    "source_occupancy_percent": image_metrics(model_source).occupancy_percent,
                    "model_occupancy_percent": image_metrics(
                        simulated_model_input
                    ).occupancy_percent,
                    "beam_candidates": list(
                        dict.fromkeys(
                            [outcome.raw_text or outcome.text, outcome.text]
                            + [candidate.text for candidate in outcome.alternatives]
                        )
                    ),
                }
            )
        results.append(
            {
                "variant": asdict(variant),
                "metrics": {
                    domain: summarize(records, domain)
                    for domain in ("historical", "touchscreen", "touchscreen-segment")
                },
                "samples": records,
            }
        )
    return {
        "model": settings.model_name,
        "processor_use_fast": settings.processor_use_fast,
        "beam_width": settings.beam_width,
        "variants": results,
        "wall_time_ms": (time.perf_counter() - benchmark_started) * 1000,
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# TouchWrite preprocessing benchmark",
        "",
        f"Model: `{report['model']}`",
        "",
        "| Variant | Historical exact | Touchscreen exact | Touchscreen CER | "
        "Short-word exact | Segment exact | Segment CER | Median ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in report["variants"]:
        metrics = result["metrics"]
        historical = metrics["historical"]
        touchscreen = metrics["touchscreen"]
        segments = metrics["touchscreen-segment"]
        lines.append(
            "| {name} | {historical:.1%} | {touchscreen:.1%} | {cer:.1%} | "
            "{short_exact} | {segment_exact:.1%} | {segment_cer:.1%} | {latency:.0f} |".format(
                name=result["variant"]["name"],
                historical=historical["exact_accuracy"] or 0.0,
                touchscreen=touchscreen["exact_accuracy"] or 0.0,
                cer=touchscreen["cer"] or 0.0,
                short_exact=(
                    f"{touchscreen['short_word_accuracy']:.1%}"
                    if touchscreen["short_word_accuracy"] is not None
                    else "--"
                ),
                segment_exact=segments["exact_accuracy"] or 0.0,
                segment_cer=segments["cer"] or 0.0,
                latency=touchscreen["median_latency_ms"] or 0.0,
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--historical",
        type=Path,
        default=Path("tests/fixtures/historical_accuracy.json"),
    )
    parser.add_argument(
        "--touchscreen",
        type=Path,
        default=Path("tests/fixtures/touchscreen_accuracy.json"),
    )
    parser.add_argument(
        "--accuracy-session",
        type=Path,
        help="use a collect_accuracy session instead of the legacy touchscreen manifest",
    )
    parser.add_argument(
        "--variants",
        nargs="*",
        choices=[variant.name for variant in VARIANTS],
        help="run a named subset; the default runs the complete bounded grid",
    )
    parser.add_argument(
        "--output-json", type=Path, default=Path("reports/preprocessing_benchmark.json")
    )
    parser.add_argument(
        "--output-md", type=Path, default=Path("reports/preprocessing_benchmark.md")
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = Settings.from_environment()
    items = load_evaluation_items(args.historical, args.touchscreen, settings.data_dir)
    if args.accuracy_session is not None:
        historical = [item for item in items if item["domain"] == "historical"]
        items = historical + load_accuracy_session_items(args.accuracy_session)
    variants = (
        tuple(variant for variant in VARIANTS if variant.name in args.variants)
        if args.variants
        else VARIANTS
    )
    report = benchmark(items, settings, variants)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown(report, args.output_md)
    print(json.dumps({"variants": len(report["variants"]), "items": len(items)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
