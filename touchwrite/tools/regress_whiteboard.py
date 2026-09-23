"""Run golden trajectories through the complete authoritative recognition pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from touchwrite.config.settings import Settings
from touchwrite.ink.renderer import InkRenderer
from touchwrite.ink.smoother import MovingAverageSmoother
from touchwrite.persistence.session_store import SessionStore
from touchwrite.recognition.image_recognizer import ImageHandwritingRecognizer
from touchwrite.services.handwriting_service import HandwritingService


def run(manifest_path: Path, data_dir: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pipeline = manifest["pipeline"]
    recognizer = ImageHandwritingRecognizer(
        model_name=str(pipeline["model_name"]),
        device="auto",
        beam_width=int(pipeline["beam_width"]),
        max_new_tokens=int(pipeline["max_new_tokens"]),
        processor_use_fast=bool(pipeline["processor_use_fast"]),
    )
    service = HandwritingService(
        recognizer,
        InkRenderer(
            int(pipeline["render_width"]),
            int(pipeline["render_height"]),
            int(pipeline["render_padding"]),
            int(pipeline["stroke_width"]),
        ),
        None,
        MovingAverageSmoother(int(pipeline["smoothing_window"])),
    )
    store = SessionStore(data_dir)
    rows: list[dict[str, object]] = []
    for fixture in manifest["samples"]:
        word = store.load(str(fixture["word_id"]))
        outcome = service.commit(word, "")
        rows.append(
            {
                **fixture,
                "after_prediction": outcome.inserted_text,
                "passed": outcome.inserted_text == fixture["expected"],
                "latency_ms": outcome.result.inference_duration_ms,
            }
        )
    return {"passed": all(bool(row["passed"]) for row in rows), "samples": rows}


def main() -> int:
    settings = Settings.from_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/fixtures/whiteboard_regression.json"),
    )
    parser.add_argument("--data-dir", type=Path, default=settings.data_dir)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = run(arguments.manifest, arguments.data_dir)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
