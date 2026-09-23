"""Run the separately labeled current touchscreen capture regression suite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from touchwrite.config.settings import Settings
from touchwrite.diagnostics.accuracy import character_error_count, replay_sample
from touchwrite.tools.replay_sample import build_service

DEFAULT_FIXTURE = Path("tests/fixtures/touchscreen_regression.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=Path("reports/touchscreen_replay"))
    parser.add_argument("--determinism-runs", type=int, default=5)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    fixture: dict[str, Any] = json.loads(args.fixture.read_text(encoding="utf-8"))
    settings = Settings.from_environment()
    output_root = args.output.resolve()
    service = build_service(settings, output_root / "debug")
    samples = []
    for item in fixture["samples"]:
        sample_id = item["sample_id"]
        sample_dir = settings.data_dir / sample_id
        if not (sample_dir / "trajectory.json").is_file():
            samples.append({**item, "available": False})
            continue
        result = replay_sample(
            sample_dir,
            output_root / sample_id,
            service,
            expected=item["expected"],
            determinism_runs=max(1, args.determinism_runs),
        )
        prediction = result["paths"]["commit"]["prediction"]
        samples.append(
            {
                "available": True,
                "sample_id": sample_id,
                "expected": item["expected"],
                "live_prediction": result["live_prediction"],
                "replay_prediction": prediction,
                "v1_style_prediction": result["paths"]["v1"]["prediction"],
                "preview_prediction": result["paths"]["preview"]["prediction"],
                "commit_prediction": prediction,
                "exact": prediction == item["expected"],
                "character_errors": character_error_count(item["expected"], prediction),
                "reference_characters": len(item["expected"]),
                "deterministic": result["determinism"]["stable"],
                "pixel_identical": result["pixel_comparisons"]["v1_vs_commit"][
                    "pixel_identical"
                ],
                "trajectory_hash": result["trajectory"]["trajectory_hash"],
            }
        )
    available = [sample for sample in samples if sample.get("available")]
    exact_count = sum(bool(sample["exact"]) for sample in available)
    errors = sum(int(sample["character_errors"]) for sample in available)
    characters = sum(int(sample["reference_characters"]) for sample in available)
    report = {
        "suite": "current-touchscreen-capture",
        "sample_count": len(available),
        "exact_word_accuracy": exact_count / len(available) if available else None,
        "character_error_rate": errors / characters if characters else None,
        "samples": samples,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "regression.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(sample.get("deterministic", True) for sample in available) else 1


if __name__ == "__main__":
    raise SystemExit(main())

