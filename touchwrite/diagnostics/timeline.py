"""Low-volume recognition lifecycle tracing for snapshot sequencing diagnostics."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class RecognitionTimeline:
    """Record lifecycle transitions without logging high-volume pointer updates."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []

    @property
    def records(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(dict(record) for record in self._records)

    def record(self, event: str, **details: Any) -> None:
        record = {
            "event": event,
            "monotonic_ns": time.monotonic_ns(),
            **details,
        }
        with self._lock:
            self._records.append(record)
            if self.path is None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

