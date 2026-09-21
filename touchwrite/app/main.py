"""TouchWrite executable entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from touchwrite.config.settings import Settings
from touchwrite.ui.main_window import MainWindow
from touchwrite.utils.logging import configure_logging


def main() -> int:
    settings = Settings.from_environment()
    configure_logging(settings.log_level)
    app = QApplication(sys.argv)
    app.setApplicationName("TouchWrite")
    window = MainWindow(settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

