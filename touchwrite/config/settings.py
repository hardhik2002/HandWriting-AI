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
    input_mode: str = "auto"
    smoothing_enabled: bool = True
    smoothing_window: int = 3
    two_finger_tap_max_ms: int = 220
    two_finger_max_travel: float = 0.035
    two_finger_overlap_min_ms: int = 25
    min_stroke_points: int = 2
    render_width: int = 512
    render_height: int = 128
    render_padding: int = 16
    stroke_width: int = 8
    visual_stroke_width: int = 4
    model_name: str = "microsoft/trocr-base-handwritten"
    model_device: str = "auto"
    beam_width: int = 8
    max_new_tokens: int = 24
    processor_use_fast: bool = False
    preview_debounce_ms: int = 500
    autosave_interval_ms: int = 1500
    autosave_enabled: bool = True
    save_samples: bool = True
    debug_input: bool = False
    debug_recognition: bool = False
    data_dir: Path = Path("data/handwriting")
    autosave_path: Path = Path("data/documents/latest.json")
    debug_recognition_dir: Path = Path("data/debug/recognition")
    touchscreen_debug_dir: Path = Path("data/debug/touchscreen")
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if self.input_mode not in {"auto", "mouse", "touchpad", "touchscreen"}:
            raise ValueError("input_mode must be auto, mouse, touchpad, or touchscreen")
        if self.smoothing_window < 1 or self.smoothing_window % 2 == 0:
            raise ValueError("smoothing_window must be a positive odd number")
        if self.render_width <= 0 or self.render_height <= 0:
            raise ValueError("render dimensions must be positive")
        if self.render_padding < 0 or 2 * self.render_padding >= min(
            self.render_width, self.render_height
        ):
            raise ValueError("render padding must leave a non-empty drawing region")
        if self.beam_width < 1 or self.max_new_tokens < 1:
            raise ValueError("generation limits must be positive")
        if self.visual_stroke_width < 1:
            raise ValueError("visual_stroke_width must be positive")
        if self.preview_debounce_ms < 0 or self.autosave_interval_ms < 1:
            raise ValueError("preview and autosave timing values must not be negative")

    @classmethod
    def from_environment(cls) -> Settings:
        prefix = "TOUCHWRITE_"
        values: dict[str, object] = {}
        bool_names = {
            "smoothing_enabled",
            "processor_use_fast",
            "save_samples",
            "debug_input",
            "debug_recognition",
            "autosave_enabled",
        }
        int_names = {
            "smoothing_window",
            "two_finger_tap_max_ms",
            "two_finger_overlap_min_ms",
            "min_stroke_points",
            "render_width",
            "render_height",
            "render_padding",
            "stroke_width",
            "visual_stroke_width",
            "beam_width",
            "max_new_tokens",
            "preview_debounce_ms",
            "autosave_interval_ms",
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
            elif field.name in {
                "data_dir",
                "debug_recognition_dir",
                "touchscreen_debug_dir",
                "autosave_path",
            }:
                values[field.name] = Path(raw)
            else:
                values[field.name] = raw
        return cls(**values)
