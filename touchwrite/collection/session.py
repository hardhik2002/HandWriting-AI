"""Append-only manifests for guided, labeled handwriting collection sessions."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

COLLECTION_CATEGORIES: dict[str, tuple[str, ...]] = {
    "uppercase": tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    "lowercase": tuple("abcdefghijklmnopqrstuvwxyz"),
    "digits": tuple("0123456789"),
    "short_words": (
        "hi",
        "I",
        "am",
        "are",
        "how",
        "you",
        "the",
        "to",
        "in",
        "on",
        "of",
        "is",
    ),
    "common_english": (
        "hello",
        "where",
        "today",
        "please",
        "thanks",
        "writing",
        "screen",
        "recognition",
    ),
    "technical": (
        "TouchWrite",
        "hardhik",
        "Python",
        "model",
        "tensor",
        "trajectory",
        "touchscreen",
        "diagnostics",
    ),
}


def create_session(
    root: Path,
    *,
    participant: str = "local-user",
    repeats: int = 3,
    session_id: str | None = None,
) -> Path:
    """Create a prompt queue without changing any existing handwriting samples."""
    if repeats < 1:
        raise ValueError("repeats must be positive")
    identifier = session_id or f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    session_dir = root / identifier
    if session_dir.exists():
        raise FileExistsError(f"collection session already exists: {session_dir}")
    session_dir.mkdir(parents=True)
    prompts = [
        {"category": category, "label": label, "repeat": repeat}
        for category, labels in COLLECTION_CATEGORIES.items()
        for label in labels
        for repeat in range(1, repeats + 1)
    ]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "session_id": identifier,
        "participant": participant,
        "created_at": datetime.now(UTC).isoformat(),
        "repeats": repeats,
        "prompts": prompts,
        "samples": [],
    }
    _write_json_atomic(session_dir / "session.json", payload)
    return session_dir


def load_session(session_dir: Path) -> dict[str, Any]:
    return json.loads((session_dir / "session.json").read_text(encoding="utf-8"))


def add_sample(
    session_dir: Path,
    handwriting_root: Path,
    sample_id: str,
    label: str,
) -> dict[str, Any]:
    """Add a label and immutable artifact references to a collection manifest."""
    label = label.strip()
    if not label:
        raise ValueError("label must not be empty")
    sample_dir = handwriting_root / sample_id
    required = ("trajectory.json", "metadata.json", "raw.png", "processed.png")
    missing = [name for name in required if not (sample_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"sample {sample_id} is missing: {', '.join(missing)}")
    payload = load_session(session_dir)
    if any(record["sample_id"] == sample_id for record in payload["samples"]):
        raise ValueError(f"sample is already in this session: {sample_id}")
    metadata = json.loads((sample_dir / "metadata.json").read_text(encoding="utf-8"))
    record = {
        "session_id": payload["session_id"],
        "sample_id": sample_id,
        "label": label,
        "prediction": metadata.get("prediction"),
        "raw_prediction": metadata.get("raw_prediction"),
        "model_name": metadata.get("model_name"),
        "trajectory": str((sample_dir / "trajectory.json").resolve()),
        "raw_image": str((sample_dir / "raw.png").resolve()),
        "processed_image": str((sample_dir / "processed.png").resolve()),
        "added_at": datetime.now(UTC).isoformat(),
    }
    payload["samples"].append(record)
    _write_json_atomic(session_dir / "session.json", payload)
    return record


def collection_status(session_dir: Path) -> dict[str, Any]:
    payload = load_session(session_dir)
    collected: dict[tuple[str, str], int] = {}
    prompt_lookup = {prompt["label"]: prompt["category"] for prompt in payload["prompts"]}
    for record in payload["samples"]:
        label = record["label"]
        category = prompt_lookup.get(label, "unplanned")
        key = (category, label)
        collected[key] = collected.get(key, 0) + 1
    next_prompt = next(
        (
            prompt
            for prompt in payload["prompts"]
            if collected.get((prompt["category"], prompt["label"]), 0) < prompt["repeat"]
        ),
        None,
    )
    return {
        "session_id": payload["session_id"],
        "collected": len(payload["samples"]),
        "target": len(payload["prompts"]),
        "next_prompt": next_prompt,
    }


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
