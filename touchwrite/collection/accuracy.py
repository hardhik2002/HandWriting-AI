"""Guided touchscreen accuracy sessions and baseline reporting."""

from __future__ import annotations

import html
import json
import os
import random
import statistics
import tempfile
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image

from touchwrite.diagnostics.accuracy import image_metrics, trajectory_metrics
from touchwrite.ink.models import HandwrittenWord
from touchwrite.recognition.base import RecognitionResult

REQUIRED_WORDS = (
    "hi",
    "how",
    "are",
    "you",
    "I",
    "am",
    "hardhik",
    "hello",
    "world",
    "this",
    "that",
    "there",
    "where",
    "what",
    "when",
    "who",
    "why",
    "is",
    "it",
    "in",
    "to",
    "the",
    "and",
    "with",
    "from",
    "good",
    "morning",
    "today",
    "python",
    "code",
    "model",
    "engineer",
    "touch",
    "write",
    "screen",
    "computer",
    "windows",
)
ISOLATED_CHARACTERS = ("a", "e", "i", "o", "u", "h", "k", "l", "m", "n", "r", "s", "t")
AMBIGUOUS_GLYPHS = ("I", "1", "l")
DIFFICULT_WORDS = ("hi", "is", "it", "in", "I", "am", "hardhik")
DIFFICULT_REPETITIONS = 10


def build_accuracy_prompts(session_id: str) -> list[dict[str, Any]]:
    """Build a deterministic, distributed queue of roughly one hundred real targets."""
    randomizer = random.Random(session_id)
    initial = [
        *(dict(category="word", expected=label) for label in REQUIRED_WORDS),
        *(
            dict(category="isolated_character", expected=label)
            for label in ISOLATED_CHARACTERS
        ),
        *(dict(category="ambiguous_glyph", expected=label) for label in AMBIGUOUS_GLYPHS),
    ]
    randomizer.shuffle(initial)
    prompts = initial
    counts = Counter(prompt["expected"] for prompt in prompts)
    while any(counts[label] < DIFFICULT_REPETITIONS for label in DIFFICULT_WORDS):
        repetition_round = [
            dict(category="difficult_short_word", expected=label)
            for label in DIFFICULT_WORDS
            if counts[label] < DIFFICULT_REPETITIONS
        ]
        randomizer.shuffle(repetition_round)
        prompts.extend(repetition_round)
        counts.update(prompt["expected"] for prompt in repetition_round)
    occurrence: Counter[str] = Counter()
    output = []
    for index, prompt in enumerate(prompts, start=1):
        label = prompt["expected"]
        occurrence[label] += 1
        output.append(
            {
                "prompt_id": f"p{index:03d}",
                "sequence": index,
                "category": prompt["category"],
                "expected": label,
                "label_repetition": occurrence[label],
                "status": "pending",
            }
        )
    return output


def create_accuracy_session(
    root: Path,
    *,
    participant: str = "local-user",
    session_id: str | None = None,
) -> Path:
    identifier = session_id or f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    session_dir = root / identifier
    if session_dir.exists():
        raise FileExistsError(f"accuracy session already exists: {session_dir}")
    (session_dir / "samples").mkdir(parents=True)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "kind": "touchscreen-accuracy",
        "session_id": identifier,
        "participant": participant,
        "created_at": datetime.now(UTC).isoformat(),
        "input_mode": "touchscreen",
        "prompts": build_accuracy_prompts(identifier),
        "samples": [],
    }
    _write_json_atomic(session_dir / "manifest.json", manifest)
    return session_dir


def load_accuracy_session(session_dir: Path) -> dict[str, Any]:
    return json.loads((session_dir / "manifest.json").read_text(encoding="utf-8"))


def next_accuracy_prompt(manifest: dict[str, Any]) -> dict[str, Any] | None:
    return next((prompt for prompt in manifest["prompts"] if prompt["status"] == "pending"), None)


def record_accuracy_sample(
    session_dir: Path,
    prompt_id: str,
    word: HandwrittenWord,
    raw_image: Image.Image,
    processed_image: Image.Image,
    result: RecognitionResult,
) -> dict[str, Any]:
    """Persist one model-independent label and all exact recognition artifacts."""
    manifest = load_accuracy_session(session_dir)
    prompt = next(
        (item for item in manifest["prompts"] if item["prompt_id"] == prompt_id), None
    )
    if prompt is None:
        raise KeyError(f"unknown prompt: {prompt_id}")
    if prompt["status"] != "pending":
        raise ValueError(f"prompt is already completed: {prompt_id}")
    expected = str(prompt["expected"])
    if word.expected_text != expected:
        raise ValueError("word label must match the displayed target")
    sample_dir = session_dir / "samples" / word.word_id
    sample_dir.mkdir(parents=True, exist_ok=True)
    model_input_path = sample_dir / "model_input.png"
    model_stats_path = sample_dir / "model_input.json"
    if not model_input_path.is_file() or not model_stats_path.is_file():
        raise FileNotFoundError("recognizer did not preserve the exact model input")

    raw_image.save(sample_dir / "raw.png")
    processed_image.save(sample_dir / "processed.png")
    _tight_crop(processed_image).save(sample_dir / "cropped.png")
    _write_json_atomic(sample_dir / "trajectory.json", word.to_dict())
    candidates = [
        {
            "text": result.raw_text or result.text,
            "score": next(
                (
                    candidate.score
                    for candidate in result.alternatives
                    if candidate.text == (result.raw_text or result.text)
                ),
                result.sequence_score if (result.raw_text or result.text) == result.text else None,
            ),
        },
        *(
            {"text": candidate.text, "score": candidate.score}
            for candidate in result.alternatives
        ),
    ]
    candidates = list({candidate["text"]: candidate for candidate in candidates}.values())
    result_payload = {
        "expected": expected,
        "prediction": result.text,
        "raw_prediction": result.raw_text,
        "sequence_score": result.sequence_score,
        "beam_candidates": candidates,
        "model_name": result.model_name,
        "device": result.device,
        "processor_mode": result.processor_mode,
        "generation_settings": result.generation_settings,
        "latency_ms": result.inference_duration_ms,
        "processing_duration_ms": result.processing_duration_ms,
        "generation_duration_ms": result.generation_duration_ms,
        "decoding_duration_ms": result.decoding_duration_ms,
    }
    _write_json_atomic(sample_dir / "result.json", result_payload)
    model_stats = json.loads(model_stats_path.read_text(encoding="utf-8"))
    preprocessing_path = sample_dir / "preprocessing.json"
    preprocessing = (
        json.loads(preprocessing_path.read_text(encoding="utf-8"))
        if preprocessing_path.is_file()
        else {}
    )
    trajectory = trajectory_metrics(word)
    physical = _physical_geometry(word, trajectory)
    with Image.open(model_input_path) as model_input_image:
        model_input_metrics = _metrics_payload(model_input_image)
    record = {
        "prompt_id": prompt_id,
        "sequence": prompt["sequence"],
        "category": prompt["category"],
        "label_repetition": prompt["label_repetition"],
        "sample_id": word.word_id,
        "session_id": manifest["session_id"],
        "expected": expected,
        "prediction": result.text,
        "raw_prediction": result.raw_text,
        "exact": result.text == expected,
        "created_at": word.created_at,
        "trajectory_metrics": trajectory,
        "physical_geometry": physical,
        "processed_image_metrics": _metrics_payload(processed_image),
        "model_input_metrics": model_input_metrics,
        "processor_tensor_statistics": model_stats,
        "preprocessing": preprocessing,
        "result": result_payload,
        "artifacts": {
            "trajectory": _relative(session_dir, sample_dir / "trajectory.json"),
            "raw_image": _relative(session_dir, sample_dir / "raw.png"),
            "processed_image": _relative(session_dir, sample_dir / "processed.png"),
            "cropped_image": _relative(session_dir, sample_dir / "cropped.png"),
            "model_input_image": _relative(session_dir, model_input_path),
            "model_input_statistics": _relative(session_dir, model_stats_path),
            "preprocessing": _relative(session_dir, preprocessing_path),
            "result": _relative(session_dir, sample_dir / "result.json"),
        },
    }
    prompt["status"] = "completed"
    prompt["sample_id"] = word.word_id
    manifest["samples"].append(record)
    manifest["updated_at"] = datetime.now(UTC).isoformat()
    _write_json_atomic(session_dir / "manifest.json", manifest)
    write_diagnostic_index(session_dir, manifest)
    return record


def evaluate_accuracy_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    samples = manifest.get("samples", [])
    total_characters = 0
    character_edits = Counter()
    word_edits = Counter()
    confusions: Counter[str] = Counter()
    exact = 0
    length_groups: dict[str, list[bool]] = {
        "1": [],
        "2": [],
        "3-4": [],
        "5-7": [],
        "8+": [],
    }
    latencies = []
    for sample in samples:
        expected = sample["expected"]
        prediction = sample["prediction"]
        is_exact = expected == prediction
        exact += int(is_exact)
        total_characters += len(expected)
        operations = edit_operations(list(expected), list(prediction))
        character_edits.update(operation for operation, _, _ in operations)
        for operation, left, right in operations:
            if operation == "substitution":
                confusions[f"{left} -> {right}"] += 1
            elif operation == "deletion":
                confusions[f"{left} -> <deleted>"] += 1
            elif operation == "insertion":
                confusions[f"<inserted> -> {right}"] += 1
        word_edits.update(
            operation
            for operation, _, _ in edit_operations(expected.split(), prediction.split())
        )
        length_groups[_length_group(len(expected))].append(is_exact)
        latency = sample.get("result", {}).get("latency_ms")
        if latency is not None:
            latencies.append(float(latency))
    character_error_count = sum(character_edits.values())
    word_error_count = sum(word_edits.values())
    expected_words = sum(len(sample["expected"].split()) for sample in samples)
    return {
        "session_id": manifest["session_id"],
        "sample_count": len(samples),
        "target_sample_count": len(manifest["prompts"]),
        "complete": len(samples) == len(manifest["prompts"]),
        "exact_accuracy": exact / len(samples) if samples else None,
        "cer": character_error_count / total_characters if total_characters else None,
        "wer": word_error_count / expected_words if expected_words else None,
        "insertions": character_edits["insertion"],
        "deletions": character_edits["deletion"],
        "substitutions": character_edits["substitution"],
        "average_word_length": (
            statistics.mean(len(sample["expected"]) for sample in samples) if samples else None
        ),
        "accuracy_by_word_length": {
            group: {
                "samples": len(values),
                "exact_accuracy": sum(values) / len(values) if values else None,
            }
            for group, values in length_groups.items()
        },
        "short_word_accuracy": (
            sum(value for group in ("1", "2") for value in length_groups[group])
            / sum(len(length_groups[group]) for group in ("1", "2"))
            if any(length_groups[group] for group in ("1", "2"))
            else None
        ),
        "character_confusions": [
            {"pair": pair, "count": count}
            for pair, count in confusions.most_common()
        ],
        "median_latency_ms": statistics.median(latencies) if latencies else None,
        "p95_latency_ms": _percentile(latencies, 0.95) if latencies else None,
        "samples": [
            {
                "prompt_id": sample["prompt_id"],
                "sample_id": sample["sample_id"],
                "expected": sample["expected"],
                "prediction": sample["prediction"],
                "exact": sample["exact"],
            }
            for sample in samples
        ],
    }


def write_baseline_reports(
    session_dir: Path,
    json_path: Path = Path("reports/touchscreen_baseline.json"),
    markdown_path: Path = Path("reports/touchscreen_baseline.md"),
) -> dict[str, Any]:
    manifest = load_accuracy_session(session_dir)
    report = evaluate_accuracy_manifest(manifest)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(json_path, report)
    lines = [
        "# Touchscreen recognition baseline",
        "",
        f"Session: `{report['session_id']}`",
        "",
        f"Progress: {report['sample_count']} / {report['target_sample_count']} real samples",
        "",
    ]
    if not report["sample_count"]:
        lines.append("No samples have been submitted yet.")
    else:
        lines.extend(
            [
                "| Metric | Value |",
                "|---|---:|",
                f"| Exact accuracy | {_percent(report['exact_accuracy'])} |",
                f"| CER | {_percent(report['cer'])} |",
                f"| WER | {_percent(report['wer'])} |",
                f"| Insertions | {report['insertions']} |",
                f"| Deletions | {report['deletions']} |",
                f"| Substitutions | {report['substitutions']} |",
                f"| Average target length | {report['average_word_length']:.2f} |",
                f"| Short-word accuracy | {_percent(report['short_word_accuracy'])} |",
                f"| Median latency | {report['median_latency_ms']:.0f} ms |",
                f"| P95 latency | {report['p95_latency_ms']:.0f} ms |",
                "",
                "## Accuracy by target length",
                "",
                "| Length | Samples | Exact accuracy |",
                "|---|---:|---:|",
            ]
        )
        for group, metrics in report["accuracy_by_word_length"].items():
            lines.append(
                f"| {group} | {metrics['samples']} | {_percent(metrics['exact_accuracy'])} |"
            )
        lines.extend(
            [
                "",
                "## Most frequent character confusions",
                "",
                "| Alignment | Count |",
                "|---|---:|",
            ]
        )
        for confusion in report["character_confusions"][:30]:
            lines.append(f"| `{confusion['pair']}` | {confusion['count']} |")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def write_diagnostic_index(session_dir: Path, manifest: dict[str, Any]) -> None:
    cards = []
    for sample in manifest["samples"]:
        artifacts = sample["artifacts"]
        images = "".join(
            f'<figure><img src="{html.escape(artifacts[key])}" loading="lazy">'
            f"<figcaption>{html.escape(label)}</figcaption></figure>"
            for key, label in (
                ("raw_image", "Raw trajectory raster"),
                ("processed_image", "Current processed image"),
                ("cropped_image", "Tight crop"),
                ("model_input_image", "Exact model input"),
            )
        )
        cards.append(
            '<article class="sample">'
            f"<h2>{html.escape(sample['expected'])} &rarr; "
            f"{html.escape(sample['prediction'])}</h2>"
            f"<p>{html.escape(sample['prompt_id'])} / {html.escape(sample['sample_id'])}</p>"
            f'<div class="images">{images}</div></article>'
        )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TouchWrite accuracy diagnostics</title>
<style>
body{{font-family:Segoe UI,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}
.sample{{background:white;border:1px solid #cbd5e1;border-radius:12px;padding:16px;margin:16px 0}}
.images{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}
figure{{margin:0}}img{{width:100%;height:190px;object-fit:contain;border:1px solid #e2e8f0}}
figcaption{{font-size:13px;color:#475569;margin-top:4px}}
</style></head><body><h1>TouchWrite touchscreen diagnostics</h1>
<p>Session {html.escape(manifest['session_id'])}; {len(manifest['samples'])} labeled samples.</p>
{''.join(cards)}</body></html>"""
    (session_dir / "index.html").write_text(document, encoding="utf-8")


def edit_operations(
    expected: Sequence[str], actual: Sequence[str]
) -> list[tuple[str, str | None, str | None]]:
    rows = len(expected) + 1
    columns = len(actual) + 1
    distance = [[0] * columns for _ in range(rows)]
    back: list[list[str | None]] = [[None] * columns for _ in range(rows)]
    for row in range(1, rows):
        distance[row][0] = row
        back[row][0] = "deletion"
    for column in range(1, columns):
        distance[0][column] = column
        back[0][column] = "insertion"
    for row in range(1, rows):
        for column in range(1, columns):
            if expected[row - 1] == actual[column - 1]:
                distance[row][column] = distance[row - 1][column - 1]
                back[row][column] = "match"
                continue
            choices = (
                (distance[row - 1][column - 1] + 1, "substitution"),
                (distance[row - 1][column] + 1, "deletion"),
                (distance[row][column - 1] + 1, "insertion"),
            )
            distance[row][column], back[row][column] = min(choices, key=lambda item: item[0])
    operations = []
    row, column = len(expected), len(actual)
    while row or column:
        operation = back[row][column]
        if operation == "match":
            row -= 1
            column -= 1
        elif operation == "substitution":
            operations.append((operation, expected[row - 1], actual[column - 1]))
            row -= 1
            column -= 1
        elif operation == "deletion":
            operations.append((operation, expected[row - 1], None))
            row -= 1
        elif operation == "insertion":
            operations.append((operation, None, actual[column - 1]))
            column -= 1
        else:
            raise RuntimeError("invalid alignment state")
    operations.reverse()
    return operations


def _tight_crop(image: Image.Image, threshold: int = 250) -> Image.Image:
    grayscale = image.convert("L")
    bounds = grayscale.point(lambda value: 255 if value < threshold else 0).getbbox()
    return grayscale.crop(bounds) if bounds is not None else grayscale.copy()


def _physical_geometry(word: HandwrittenWord, metrics: dict[str, Any]) -> dict[str, Any]:
    bounds = metrics.get("raw_bbox") or {}
    dpi_x = word.recognition_metadata.get("physical_dpi_x")
    dpi_y = word.recognition_metadata.get("physical_dpi_y")
    width = bounds.get("width")
    height = bounds.get("height")
    return {
        "physical_dpi_x": dpi_x,
        "physical_dpi_y": dpi_y,
        "width_mm": width / dpi_x * 25.4 if width is not None and dpi_x else None,
        "height_mm": height / dpi_y * 25.4 if height is not None and dpi_y else None,
    }


def _metrics_payload(image: Image.Image) -> dict[str, Any]:
    metrics = image_metrics(image)
    return {
        key: getattr(metrics, key)
        for key in metrics.__dataclass_fields__
    }


def _length_group(length: int) -> str:
    if length <= 1:
        return "1"
    if length == 2:
        return "2"
    if length <= 4:
        return "3-4"
    if length <= 7:
        return "5-7"
    return "8+"


def _percent(value: float | None) -> str:
    return "--" if value is None else f"{value:.1%}"


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
