"""TouchWrite executable entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from touchwrite.config.settings import Settings
from touchwrite.ink.renderer import InkRenderer
from touchwrite.ink.smoother import MovingAverageSmoother
from touchwrite.persistence.session_store import SessionStore
from touchwrite.recognition.image_recognizer import ImageHandwritingRecognizer
from touchwrite.services.handwriting_service import HandwritingService
from touchwrite.ui.main_window import MainWindow
from touchwrite.utils.logging import configure_logging


def main() -> int:
    settings = Settings.from_environment()
    configure_logging(settings.log_level)
    app = QApplication(sys.argv)
    app.setApplicationName("TouchWrite")
    renderer = InkRenderer(
        settings.render_width,
        settings.render_height,
        settings.render_padding,
        settings.stroke_width,
    )
    debug_dir = None
    if settings.debug_input:
        debug_dir = settings.touchscreen_debug_dir
    elif settings.debug_recognition:
        debug_dir = settings.debug_recognition_dir
    recognizer = ImageHandwritingRecognizer(
        settings.model_name,
        settings.model_device,
        settings.beam_width,
        settings.max_new_tokens,
        settings.processor_use_fast,
        debug_dir,
    )
    store = SessionStore(settings.data_dir) if settings.save_samples else None
    smoother = (
        MovingAverageSmoother(settings.smoothing_window) if settings.smoothing_enabled else None
    )
    service = HandwritingService(recognizer, renderer, store, smoother, debug_dir=debug_dir)
    window = MainWindow(settings, service)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
