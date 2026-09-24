"""Launch the guided real-touchscreen recognition benchmark collector."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import QApplication

from touchwrite.collection.accuracy import create_accuracy_session, write_baseline_reports
from touchwrite.config.settings import Settings
from touchwrite.ink.renderer import InkRenderer
from touchwrite.ink.smoother import MovingAverageSmoother
from touchwrite.recognition.image_recognizer import ImageHandwritingRecognizer
from touchwrite.services.handwriting_service import HandwritingService
from touchwrite.ui.accuracy_collector import AccuracyCollectorWindow
from touchwrite.utils.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/accuracy"))
    parser.add_argument("--participant", default="local-user")
    parser.add_argument("--session-id")
    parser.add_argument("--resume", type=Path)
    parser.add_argument(
        "--baseline-json", type=Path, default=Path("reports/touchscreen_baseline.json")
    )
    parser.add_argument(
        "--baseline-md", type=Path, default=Path("reports/touchscreen_baseline.md")
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = replace(
        Settings.from_environment(),
        input_mode="touchscreen",
        auto_detect_input=False,
        save_samples=False,
        autosave_enabled=False,
        debug_input=False,
        debug_recognition=True,
    )
    configure_logging(settings.log_level)
    session_dir = args.resume or create_accuracy_session(
        args.root, participant=args.participant, session_id=args.session_id
    )
    if not (session_dir / "manifest.json").is_file():
        raise FileNotFoundError(f"accuracy session has no manifest: {session_dir}")
    sample_root = session_dir / "samples"
    recognizer = ImageHandwritingRecognizer(
        settings.model_name,
        settings.model_device,
        settings.beam_width,
        settings.max_new_tokens,
        settings.processor_use_fast,
        sample_root,
    )
    renderer = InkRenderer(
        settings.render_width,
        settings.render_height,
        settings.render_padding,
        settings.stroke_width,
    )
    smoother = (
        MovingAverageSmoother(settings.smoothing_window)
        if settings.smoothing_enabled
        else None
    )
    service = HandwritingService(
        recognizer, renderer, None, smoother, debug_dir=sample_root
    )
    write_baseline_reports(session_dir, args.baseline_json, args.baseline_md)
    application = QApplication(sys.argv)
    application.setApplicationName("TouchWrite Accuracy Collector")
    window = AccuracyCollectorWindow(
        settings,
        service,
        session_dir,
        baseline_json=args.baseline_json,
        baseline_markdown=args.baseline_md,
    )
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
