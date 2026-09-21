from __future__ import annotations

from PIL import Image

from tests.helpers import stroke
from touchwrite.ink.models import HandwrittenWord
from touchwrite.persistence.session_store import SessionStore


def test_save_load_and_correction(tmp_path) -> None:
    store = SessionStore(tmp_path)
    word = HandwrittenWord([stroke()], predicted_text="helo", raw_prediction="helo")
    image = Image.new("L", (20, 10), 255)
    sample_dir = store.save(word, image, image)
    assert (sample_dir / "trajectory.json").exists()
    loaded = store.load(word.word_id)
    assert loaded.predicted_text == "helo"
    assert len(loaded.strokes[0].points) == 2
    store.update_correction(word.word_id, "hello")
    assert store.load(word.word_id).expected_text == "hello"

