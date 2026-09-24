from __future__ import annotations

import json
from pathlib import Path

import pytest

from touchwrite.collection.session import add_sample, collection_status, create_session


def _sample(root: Path, sample_id: str) -> None:
    sample = root / sample_id
    sample.mkdir(parents=True)
    (sample / "trajectory.json").write_text("{}", encoding="utf-8")
    (sample / "metadata.json").write_text(
        json.dumps(
            {
                "prediction": "helo",
                "raw_prediction": " helo",
                "model_name": "test-model",
            }
        ),
        encoding="utf-8",
    )
    (sample / "raw.png").write_bytes(b"raw")
    (sample / "processed.png").write_bytes(b"processed")


def test_collection_session_records_artifacts_and_predictions(tmp_path: Path) -> None:
    handwriting = tmp_path / "handwriting"
    _sample(handwriting, "sample-one")
    session = create_session(
        tmp_path / "collection", repeats=1, session_id="session-one"
    )

    record = add_sample(session, handwriting, "sample-one", "hello")
    status = collection_status(session)

    assert record["session_id"] == "session-one"
    assert record["label"] == "hello"
    assert record["prediction"] == "helo"
    assert Path(record["trajectory"]).is_file()
    assert Path(record["raw_image"]).is_file()
    assert Path(record["processed_image"]).is_file()
    assert status["collected"] == 1


def test_collection_session_rejects_duplicate_sample(tmp_path: Path) -> None:
    handwriting = tmp_path / "handwriting"
    _sample(handwriting, "sample-one")
    session = create_session(
        tmp_path / "collection", repeats=1, session_id="session-one"
    )
    add_sample(session, handwriting, "sample-one", "hello")

    with pytest.raises(ValueError, match="already"):
        add_sample(session, handwriting, "sample-one", "hello")
