"""Typed, environment-driven TouchWrite settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    input_mode: str = "mouse"
    smoothing_enabled: bool = True
    smoothing_window: int = 3
    two_finger_tap_max_ms: int = 220
    two_finger_max_travel: float = 0.035
    two_finger_overlap_min_ms: int = 25
    min_stroke_points: int = 2
    render_width: int = 512
    render_height: int = 192
    render_padding: int = 24
    stroke_width: int = 8
    model_name: str = "microsoft/trocr-base-handwritten"
    model_device: str = "auto"
    beam_width: int = 4
    save_samples: bool = True
    debug_input: bool = False
    data_dir: Path = Path("data/handwriting")
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if self.input_mode not in {"mouse", "touchpad"}:
            raise ValueError("input_mode must be 'mouse' or 'touchpad'")
        if self.smoothing_window < 1 or self.smoothing_window % 2 == 0:
            raise ValueError("smoothing_window must be a positive odd number")
        if self.render_width <= 0 or self.render_height <= 0:
            raise ValueError("render dimensions must be positive")

    @classmethod
    def from_environment(cls) -> Settings:
        prefix = "TOUCHWRITE_"
        values: dict[str, object] = {}
        bool_names = {"smoothing_enabled", "save_samples", "debug_input"}
        int_names = {
            "smoothing_window",
            "two_finger_tap_max_ms",
            "two_finger_overlap_min_ms",
            "min_stroke_points",
            "render_width",
            "render_height",
            "render_padding",
            "stroke_width",
            "beam_width",
        }
        float_names = {"two_finger_max_travel"}
        for field in fields(cls):
            env_name = prefix + field.name.upper()
            if env_name not in os.environ:
                continue
            raw = os.environ[env_name]
            if field.name in bool_names:
                values[field.name] = _env_bool(env_name, getattr(cls(), field.name))
            elif field.name in int_names:
                values[field.name] = int(raw)
            elif field.name in float_names:
                values[field.name] = float(raw)
            elif field.name == "data_dir":
                values[field.name] = Path(raw)
            else:
                values[field.name] = raw
        return cls(**values)

