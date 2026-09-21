from __future__ import annotations

import pytest

from touchwrite.config.settings import Settings


def test_defaults_are_valid() -> None:
    settings = Settings()
    assert settings.input_mode == "mouse"
    assert settings.render_width == 512


def test_invalid_even_smoothing_window() -> None:
    with pytest.raises(ValueError, match="positive odd"):
        Settings(smoothing_window=4)


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOUCHWRITE_SAVE_SAMPLES", "false")
    monkeypatch.setenv("TOUCHWRITE_STROKE_WIDTH", "11")
    settings = Settings.from_environment()
    assert settings.save_samples is False
    assert settings.stroke_width == 11

