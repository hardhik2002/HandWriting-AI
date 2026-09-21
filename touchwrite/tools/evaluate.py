"""Evaluate a recognizer against locally corrected handwriting samples."""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from touchwrite.ink.models import HandwrittenWord
from touchwrite.recognition.base import RecognitionSample
from touchwrite.recognition.image_recognizer import ImageHandwritingRecognizer


def edit_distance(reference: str, hypothesis: str) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, reference_item in enumerate(reference, start=1):
        current = [row]
        for column, hypothesis_item in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (reference_item != hypothesis_item),
                )
            )
        previous = current
    return previous[-1]


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    samples: int
    exact_word_accuracy: float
    character_error_rate: float
    word_error_rate: float
    average_inference_latency_ms: float


def calculate_metrics(rows: list[tuple[str, str, float]]) -> EvaluationMetrics:
    if not rows:
        raise ValueError("evaluation dataset contains no labeled samples")
    exact = sum(reference == hypothesis for reference, hypothesis, _latency in rows)
    character_errors = sum(
        edit_distance(reference, hypothesis) for reference, hypothesis, _latency in rows
    )
    characters = sum(len(reference) for reference, _hypothesis, _latency in rows)
    word_errors = sum(
        edit_distance(reference.split(), hypothesis.split())
        for reference, hypothesis, _latency in rows
    )
    words = sum(len(reference.split()) for reference, _hypothesis, _latency in rows)
    return EvaluationMetrics(
        samples=len(rows),
        exact_word_accuracy=exact / len(rows),
        character_error_rate=character_errors / max(1, characters),
        word_error_rate=word_errors / max(1, words),
        average_inference_latency_ms=statistics.fmean(row[2] for row in rows),
    )


def evaluate(data_dir: Path, model_name: str, device: str, limit: int | None) -> dict[str, object]:
    recognizer = ImageHandwritingRecognizer(model_name, device)
    rows: list[tuple[str, str, float]] = []
    samples: list[dict[str, object]] = []
    for metadata_path in sorted(data_dir.glob("*/metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        expected = metadata.get("corrected_text")
        image_path = metadata_path.parent / "processed.png"
        trajectory_path = metadata_path.parent / "trajectory.json"
        if not expected or not image_path.exists() or not trajectory_path.exists():
            continue
        payload = json.loads(trajectory_path.read_text(encoding="utf-8"))
        word = HandwrittenWord.from_dict(payload)
        with Image.open(image_path) as image:
            result = recognizer.recognize(RecognitionSample(word, image.copy()))
        rows.append((str(expected), result.text, result.inference_duration_ms))
        samples.append(
            {
                "word_id": word.word_id,
                "expected": expected,
                "predicted": result.text,
                "latency_ms": result.inference_duration_ms,
            }
        )
        if limit is not None and len(rows) >= limit:
            break
    metrics = calculate_metrics(rows)
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "model": model_name,
        "metrics": asdict(metrics),
        "samples": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/handwriting"))
    parser.add_argument("--model", default="microsoft/trocr-base-handwritten")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = evaluate(arguments.data_dir, arguments.model, arguments.device, arguments.limit)
    output = arguments.output or Path("reports") / (
        f"evaluation-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

