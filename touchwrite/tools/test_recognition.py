"""Run the configured TrOCR recognizer directly against one image, bypassing the GUI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from touchwrite.ink.models import HandwrittenWord
from touchwrite.recognition.base import RecognitionSample
from touchwrite.recognition.image_recognizer import ImageHandwritingRecognizer


def run_diagnostic(
    image_path: Path,
    *,
    model_name: str,
    device: str,
    processor_use_fast: bool,
    beam_width: int,
    max_new_tokens: int,
    debug_dir: Path | None = None,
) -> dict[str, object]:
    with Image.open(image_path) as source:
        image = source.convert("RGB")
    recognizer = ImageHandwritingRecognizer(
        model_name=model_name,
        device=device,
        beam_width=beam_width,
        max_new_tokens=max_new_tokens,
        processor_use_fast=processor_use_fast,
        debug_dir=debug_dir,
    )
    word = HandwrittenWord(strokes=[], word_id=image_path.stem)
    result = recognizer.recognize(RecognitionSample(word=word, image=image))
    return {
        "image": str(image_path),
        "image_mode": image.mode,
        "image_dimensions": list(image.size),
        "model_name": result.model_name,
        "device": result.device,
        "processor_mode": result.processor_mode,
        "model_load_duration_ms": result.model_load_duration_ms,
        "processing_duration_ms": result.processing_duration_ms,
        "generation_duration_ms": result.generation_duration_ms,
        "decoding_duration_ms": result.decoding_duration_ms,
        "total_inference_duration_ms": result.inference_duration_ms,
        "raw_prediction": result.raw_text,
        "selected_prediction": result.text,
        "alternatives": [candidate.text for candidate in result.alternatives],
        "generation_settings": result.generation_settings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--model", default="microsoft/trocr-base-handwritten")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--processor", choices=("slow", "fast"), default="slow")
    parser.add_argument("--beams", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=24)
    parser.add_argument("--debug-dir", type=Path)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    if not arguments.image.is_file():
        raise SystemExit(f"image does not exist: {arguments.image}")
    report = run_diagnostic(
        arguments.image,
        model_name=arguments.model,
        device=arguments.device,
        processor_use_fast=arguments.processor == "fast",
        beam_width=arguments.beams,
        max_new_tokens=arguments.max_new_tokens,
        debug_dir=arguments.debug_dir,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
