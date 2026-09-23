"""Evidence-based replay and pixel comparison for persisted handwriting samples."""

from __future__ import annotations

import json
import math
import shutil
import time
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from touchwrite.ink.models import HandwrittenWord
from touchwrite.ink.renderer import bounding_box, filter_isolated_point_strokes, stroke_path_length
from touchwrite.recognition.base import RecognitionResult, RecognitionSample
from touchwrite.services.handwriting_service import HandwritingService
from touchwrite.services.recognition_stream import trajectory_hash


@dataclass(frozen=True, slots=True)
class ImageMetrics:
    dimensions: tuple[int, int]
    foreground_bbox: tuple[int, int, int, int] | None
    foreground_width: int
    foreground_height: int
    aspect_ratio: float | None
    padding: tuple[int, int, int, int] | None
    foreground_pixels: int
    occupancy_percent: float


def image_metrics(image: Image.Image, *, foreground_threshold: int = 250) -> ImageMetrics:
    grayscale = np.asarray(image.convert("L"))
    mask = grayscale < foreground_threshold
    height, width = mask.shape
    locations = np.argwhere(mask)
    if not locations.size:
        return ImageMetrics((width, height), None, 0, 0, None, None, 0, 0.0)
    min_y, min_x = locations.min(axis=0)
    max_y, max_x = locations.max(axis=0)
    foreground_width = int(max_x - min_x + 1)
    foreground_height = int(max_y - min_y + 1)
    bbox = (int(min_x), int(min_y), int(max_x + 1), int(max_y + 1))
    padding = (int(min_x), int(min_y), int(width - max_x - 1), int(height - max_y - 1))
    foreground_pixels = int(mask.sum())
    return ImageMetrics(
        (width, height),
        bbox,
        foreground_width,
        foreground_height,
        foreground_width / foreground_height,
        padding,
        foreground_pixels,
        foreground_pixels * 100.0 / mask.size,
    )


def compare_images(left: Image.Image, right: Image.Image) -> dict[str, Any]:
    left_array = np.asarray(left.convert("L"), dtype=np.int16)
    right_array = np.asarray(right.convert("L"), dtype=np.int16)
    if left_array.shape != right_array.shape:
        return {
            "pixel_identical": False,
            "left_shape": list(left_array.shape),
            "right_shape": list(right_array.shape),
            "different_pixels": None,
            "maximum_difference": None,
            "mean_absolute_difference": None,
        }
    difference = np.abs(left_array - right_array)
    return {
        "pixel_identical": bool(np.count_nonzero(difference) == 0),
        "left_shape": list(left_array.shape),
        "right_shape": list(right_array.shape),
        "different_pixels": int(np.count_nonzero(difference)),
        "maximum_difference": int(difference.max(initial=0)),
        "mean_absolute_difference": float(difference.mean()),
    }


def trajectory_metrics(word: HandwrittenWord) -> dict[str, Any]:
    points = [point for stroke in word.strokes for point in stroke.points]
    bounds = bounding_box(word.strokes)
    distances: list[float] = []
    velocities: list[float] = []
    for stroke in word.strokes:
        for previous, current in zip(stroke.points, stroke.points[1:], strict=False):
            distance = math.hypot(current.x_raw - previous.x_raw, current.y_raw - previous.y_raw)
            distances.append(distance)
            elapsed = (current.timestamp_ns - previous.timestamp_ns) / 1_000_000_000
            if elapsed > 0:
                velocities.append(distance / elapsed)
    retained_ids = {
        stroke.stroke_id for stroke in filter_isolated_point_strokes(word.strokes)
    }
    terminal = []
    for stroke in word.strokes[-4:]:
        stroke_bounds = bounding_box([stroke])
        terminal.append(
            {
                "stroke_id": stroke.stroke_id,
                "point_count": len(stroke.points),
                "path_length": stroke_path_length(stroke),
                "bbox": asdict(stroke_bounds) if stroke_bounds is not None else None,
                "retained_by_noise_filter": stroke.stroke_id in retained_ids,
                "duration_ms": (
                    (stroke.points[-1].timestamp_ns - stroke.points[0].timestamp_ns) / 1_000_000
                    if len(stroke.points) > 1
                    else 0.0
                ),
            }
        )
    raw_bbox = asdict(bounds) if bounds is not None else None
    if bounds is not None:
        raw_bbox["width"] = bounds.max_x - bounds.min_x
        raw_bbox["height"] = bounds.max_y - bounds.min_y
        raw_bbox["aspect_ratio"] = (bounds.max_x - bounds.min_x) / max(
            bounds.max_y - bounds.min_y, 1e-9
        )
    return {
        "stroke_count": len(word.strokes),
        "point_count": len(points),
        "trajectory_hash": trajectory_hash(word),
        "raw_bbox": raw_bbox,
        "average_points_per_stroke": len(points) / max(1, len(word.strokes)),
        "average_point_spacing": float(np.mean(distances)) if distances else 0.0,
        "median_point_spacing": float(np.median(distances)) if distances else 0.0,
        "average_velocity": float(np.mean(velocities)) if velocities else 0.0,
        "terminal_strokes": terminal,
        "filtered_stroke_ids": sorted(
            stroke.stroke_id for stroke in word.strokes if stroke.stroke_id not in retained_ids
        ),
    }


def load_sample(sample_dir: Path) -> tuple[HandwrittenWord, dict[str, Any]]:
    with (sample_dir / "trajectory.json").open("r", encoding="utf-8") as handle:
        word = HandwrittenWord.from_dict(json.load(handle))
    metadata_path = sample_dir / "metadata.json"
    metadata: dict[str, Any] = {}
    if metadata_path.is_file():
        with metadata_path.open("r", encoding="utf-8") as handle:
            metadata = json.load(handle)
    return word, metadata


def _clone_word(word: HandwrittenWord, word_id: str) -> HandwrittenWord:
    clone = deepcopy(word)
    clone.word_id = word_id
    clone.predicted_text = None
    clone.raw_prediction = None
    clone.confidence = None
    clone.model_name = None
    return clone


def _legacy_processed_image(service: HandwritingService, word: HandwrittenWord) -> Image.Image:
    """Reproduce the finalized-word flow from Git commit 8c7111f."""
    processed_word = HandwrittenWord(
        strokes=service._processed_strokes(word.strokes),
        word_id=word.word_id,
        created_at=word.created_at,
    )
    return service.renderer.render(processed_word, filter_noise=True)


def _result_payload(result: RecognitionResult) -> dict[str, Any]:
    candidates = [result.raw_text or result.text, result.text]
    candidates.extend(candidate.text for candidate in result.alternatives)
    return {
        "prediction": result.text,
        "raw_prediction": result.raw_text,
        "beam_candidates": list(dict.fromkeys(candidates)),
        "inference_duration_ms": result.inference_duration_ms,
        "processing_duration_ms": result.processing_duration_ms,
        "generation_duration_ms": result.generation_duration_ms,
        "decoding_duration_ms": result.decoding_duration_ms,
    }


def _copy_model_input(debug_dir: Path, word_id: str, destination: Path) -> Image.Image:
    source = debug_dir / word_id / "model_input.png"
    if not source.is_file():
        raise FileNotFoundError(f"recognizer did not produce {source}")
    shutil.copyfile(source, destination)
    with Image.open(destination) as image:
        return image.convert("RGB")


def replay_sample(
    sample_dir: Path,
    output_dir: Path,
    service: HandwritingService,
    *,
    expected: str | None = None,
    determinism_runs: int = 5,
) -> dict[str, Any]:
    """Replay one immutable raw trajectory through legacy, commit, and preview paths."""
    word, metadata = load_sample(sample_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = output_dir / "debug"
    service.debug_dir = debug_dir
    recognizer = service.recognizer
    if hasattr(recognizer, "debug_dir"):
        recognizer.debug_dir = debug_dir

    images: dict[str, Image.Image] = {}
    model_inputs: dict[str, Image.Image] = {}
    results: dict[str, RecognitionResult] = {}

    legacy_word = _clone_word(word, f"{word.word_id}-v1-finalized")
    images["v1"] = _legacy_processed_image(service, legacy_word)
    images["v1"].save(output_dir / "v1_processed.png")
    started = time.perf_counter()
    results["v1"] = recognizer.recognize(
        RecognitionSample(legacy_word, images["v1"], "")
    )
    legacy_wall_ms = (time.perf_counter() - started) * 1000
    model_inputs["v1"] = _copy_model_input(
        debug_dir, legacy_word.word_id, output_dir / "v1_model_input.png"
    )

    commit_word = _clone_word(word, f"{word.word_id}-v2-commit")
    commit_outcome = service.commit(commit_word, "", "")
    images["commit"] = Image.open(debug_dir / commit_word.word_id / "processed.png").convert("L")
    images["commit"].save(output_dir / "v2_commit_processed.png")
    results["commit"] = commit_outcome.result
    model_inputs["commit"] = _copy_model_input(
        debug_dir, commit_word.word_id, output_dir / "v2_commit_model_input.png"
    )

    preview_word = _clone_word(word, f"{word.word_id}-v2-preview")
    preview_outcome = service.preview(preview_word, "")
    images["preview"] = Image.open(debug_dir / preview_word.word_id / "processed.png").convert("L")
    images["preview"].save(output_dir / "v2_preview_processed.png")
    results["preview"] = preview_outcome.result
    model_inputs["preview"] = _copy_model_input(
        debug_dir, preview_word.word_id, output_dir / "v2_preview_model_input.png"
    )

    deterministic_predictions: list[str] = []
    deterministic_beams: list[list[str]] = []
    for index in range(determinism_runs):
        repeat_word = _clone_word(word, f"{word.word_id}-determinism-{index + 1}")
        result = recognizer.recognize(
            RecognitionSample(repeat_word, images["commit"], "")
        )
        deterministic_predictions.append(result.text)
        deterministic_beams.append(_result_payload(result)["beam_candidates"])

    persisted_processed: Image.Image | None = None
    persisted_path = sample_dir / "processed.png"
    if persisted_path.is_file():
        persisted_processed = Image.open(persisted_path).convert("L")

    paths_payload = {
        name: {
            **_result_payload(results[name]),
            "processed": asdict(image_metrics(images[name])),
            "model_input": asdict(image_metrics(model_inputs[name])),
        }
        for name in ("v1", "commit", "preview")
    }
    payload: dict[str, Any] = {
        "sample_id": word.word_id,
        "expected": expected or metadata.get("corrected_text") or word.expected_text,
        "live_prediction": metadata.get("prediction") or word.predicted_text,
        "document_id": metadata.get("document_id") or word.document_id,
        "line_index": metadata.get("line_index") if metadata else word.line_index,
        "word_index": metadata.get("word_index") if metadata else word.word_index,
        "commit_sequence_id": metadata.get("commit_sequence_id")
        if metadata
        else word.commit_sequence_id,
        "revision_id": metadata.get("recognition_metadata", {}).get("revision_id"),
        "trajectory": trajectory_metrics(word),
        "paths": paths_payload,
        "pixel_comparisons": {
            "v1_vs_commit": compare_images(images["v1"], images["commit"]),
            "v1_vs_preview": compare_images(images["v1"], images["preview"]),
            "commit_vs_preview": compare_images(images["commit"], images["preview"]),
            "persisted_vs_replay": compare_images(persisted_processed, images["commit"])
            if persisted_processed is not None
            else None,
            "v1_model_input_vs_commit": compare_images(
                model_inputs["v1"], model_inputs["commit"]
            ),
            "commit_model_input_vs_preview": compare_images(
                model_inputs["commit"], model_inputs["preview"]
            ),
        },
        "determinism": {
            "runs": determinism_runs,
            "predictions": deterministic_predictions,
            "beam_candidates": deterministic_beams,
            "stable": len(set(deterministic_predictions)) <= 1
            and len({tuple(beams) for beams in deterministic_beams}) <= 1,
        },
        "legacy_wall_time_ms": legacy_wall_ms,
        "legacy_source_commit": "8c7111f",
    }
    (output_dir / "replay.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def character_error_count(expected: str, actual: str) -> int:
    previous = list(range(len(actual) + 1))
    for row, expected_character in enumerate(expected, start=1):
        current = [row]
        for column, actual_character in enumerate(actual, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected_character != actual_character),
                )
            )
        previous = current
    return previous[-1]
