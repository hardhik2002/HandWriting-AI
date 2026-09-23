"""Opt-in JSONL diagnostics for touch coordinate and latency investigation."""

from __future__ import annotations

import json
import statistics
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class TouchDiagnosticRecord:
    event_type: str
    contact_id: int
    event_timestamp_ns: int
    paint_timestamp_ns: int
    event_local: tuple[float, float]
    event_global: tuple[float, float]
    transformed_canvas: tuple[float, float]
    paint_position: tuple[float, float]
    positional_error_px: float
    device_type: str
    device_pixel_ratio: float
    screen_device_pixel_ratio: float
    canvas_geometry: tuple[int, int, int, int]
    viewport_geometry: tuple[int, int, int, int] | None
    scroll_offset: tuple[int, int] | None

    @property
    def latency_ms(self) -> float:
        return max(0.0, (self.paint_timestamp_ns - self.event_timestamp_ns) / 1_000_000)


class TouchDiagnostics:
    def __init__(self, output: Path | None = None, maximum_samples: int = 1024) -> None:
        self.output = output
        self.records: deque[TouchDiagnosticRecord] = deque(maxlen=maximum_samples)

    def add(self, record: TouchDiagnosticRecord) -> None:
        self.records.append(record)
        if self.output is None:
            return
        self.output.parent.mkdir(parents=True, exist_ok=True)
        with self.output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def metrics(self) -> dict[str, Any]:
        if not self.records:
            return {"samples": 0}
        latencies = sorted(record.latency_ms for record in self.records)
        errors = [record.positional_error_px for record in self.records]
        p95_index = min(len(latencies) - 1, int(0.95 * (len(latencies) - 1)))
        return {
            "samples": len(self.records),
            "median_pointer_to_ink_latency_ms": statistics.median(latencies),
            "p95_pointer_to_ink_latency_ms": latencies[p95_index],
            "median_positional_error_px": statistics.median(errors),
            "max_positional_error_px": max(errors),
        }
