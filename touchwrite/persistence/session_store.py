"""Append-only local dataset storage."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from touchwrite.ink.models import HandwrittenWord


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(
        self,
        word: HandwrittenWord,
        raw_image: Image.Image,
        processed_image: Image.Image,
    ) -> Path:
        sample_dir = self.root / word.word_id
        if sample_dir.exists():
            raise FileExistsError(f"sample already exists: {word.word_id}")
        sample_dir.mkdir(parents=True)
        word.rendered_image_path = str(sample_dir / "processed.png")
        self._write_json_atomic(sample_dir / "trajectory.json", word.to_dict())
        metadata = {
            "word_id": word.word_id,
            "created_at": word.created_at,
            "prediction": word.predicted_text,
            "raw_prediction": word.raw_prediction,
            "corrected_text": word.expected_text,
            "confidence": word.confidence,
            "model_name": word.model_name,
        }
        self._write_json_atomic(sample_dir / "metadata.json", metadata)
        raw_image.save(sample_dir / "raw.png")
        processed_image.save(sample_dir / "processed.png")
        return sample_dir

    def load(self, word_id: str) -> HandwrittenWord:
        path = self.root / word_id / "trajectory.json"
        with path.open("r", encoding="utf-8") as handle:
            return HandwrittenWord.from_dict(json.load(handle))

    def update_correction(self, word_id: str, corrected_text: str) -> None:
        sample_dir = self.root / word_id
        metadata_path = sample_dir / "metadata.json"
        with metadata_path.open("r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        metadata["corrected_text"] = corrected_text
        self._write_json_atomic(metadata_path, metadata)
        trajectory_path = sample_dir / "trajectory.json"
        with trajectory_path.open("r", encoding="utf-8") as handle:
            trajectory = json.load(handle)
        trajectory["expected_text"] = corrected_text
        self._write_json_atomic(trajectory_path, trajectory)

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
