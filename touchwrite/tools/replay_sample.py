"""Replay a persisted trajectory through V1-finalized and V2 recognition paths."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from touchwrite.config.settings import Settings
from touchwrite.diagnostics.accuracy import replay_sample
from touchwrite.ink.renderer import InkRenderer
from touchwrite.ink.smoother import MovingAverageSmoother
from touchwrite.recognition.image_recognizer import ImageHandwritingRecognizer
from touchwrite.services.handwriting_service import HandwritingService


def build_service(settings: Settings, debug_dir: Path) -> HandwritingService:
    renderer = InkRenderer(
        settings.render_width,
        settings.render_height,
        settings.render_padding,
        settings.stroke_width,
    )
    recognizer = ImageHandwritingRecognizer(
        settings.model_name,
        settings.model_device,
        settings.beam_width,
        settings.max_new_tokens,
        settings.processor_use_fast,
        debug_dir,
    )
    smoother = (
        MovingAverageSmoother(settings.smoothing_window)
        if settings.smoothing_enabled
        else None
    )
    return HandwritingService(
        recognizer,
        renderer,
        None,
        smoother,
        debug_dir=debug_dir,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample_directory", type=Path)
    parser.add_argument("--expected")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--determinism-runs", type=int, default=5)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    sample_dir = args.sample_directory.resolve()
    if not (sample_dir / "trajectory.json").is_file():
        raise SystemExit(f"trajectory.json not found in {sample_dir}")
    output_dir = (
        args.output.resolve()
        if args.output is not None
        else (Path("reports/replay") / sample_dir.name).resolve()
    )
    settings = Settings.from_environment()
    service = build_service(settings, output_dir / "debug")
    payload = replay_sample(
        sample_dir,
        output_dir,
        service,
        expected=args.expected,
        determinism_runs=max(1, args.determinism_runs),
    )
    summary = {
        "sample_id": payload["sample_id"],
        "expected": payload["expected"],
        "stroke_count": payload["trajectory"]["stroke_count"],
        "point_count": payload["trajectory"]["point_count"],
        "trajectory_hash": payload["trajectory"]["trajectory_hash"],
        "document_id": payload["document_id"],
        "line_index": payload["line_index"],
        "word_index": payload["word_index"],
        "revision_id": payload["revision_id"],
        "commit_sequence_id": payload["commit_sequence_id"],
        "live_prediction": payload["live_prediction"],
        "v1_style_prediction": payload["paths"]["v1"]["prediction"],
        "v2_commit_prediction": payload["paths"]["commit"]["prediction"],
        "v2_preview_prediction": payload["paths"]["preview"]["prediction"],
        "beam_candidates": payload["paths"]["commit"]["beam_candidates"],
        "pixel_comparisons": payload["pixel_comparisons"],
        "deterministic": payload["determinism"]["stable"],
        "output_directory": str(output_dir),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
