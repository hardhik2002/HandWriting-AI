"""Atomic local autosave for the latest whiteboard session."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from touchwrite.document.models import WhiteboardDocument


class DocumentAutosave:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, document: WhiteboardDocument) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    document.to_dict(include_history=True),
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self) -> WhiteboardDocument | None:
        if not self.path.is_file():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return WhiteboardDocument.from_dict(value)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None
