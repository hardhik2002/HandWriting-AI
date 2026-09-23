from __future__ import annotations

import threading
import time

from touchwrite.ink.models import HandwrittenWord, Point, Stroke
from touchwrite.recognition.base import RecognitionResult
from touchwrite.services.handwriting_service import CommitOutcome
from touchwrite.services.recognition_stream import RecognitionStream, trajectory_hash


def word(offset: float = 0.0) -> HandwrittenWord:
    return HandwrittenWord(
        [
            Stroke(
                1,
                [
                    Point(0.1, 0.2, 1, 10 + offset, 20),
                    Point(0.7, 0.8, 2, 70 + offset, 80),
                ],
            )
        ]
    )


class FakeStreamingService:
    def __init__(self) -> None:
        self.preview_calls = 0
        self.commit_calls = 0
        self.cached_calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self.block_first_preview = False

    @staticmethod
    def _outcome(value: HandwrittenWord, text: str = "ink") -> CommitOutcome:
        result = RecognitionResult(text, "fake", 4.0)
        return CommitOutcome(value, result, text, None)

    def preview(self, value: HandwrittenWord, context: str = "") -> CommitOutcome:
        self.preview_calls += 1
        if self.block_first_preview and self.preview_calls == 1:
            self.started.set()
            self.release.wait(timeout=2)
        return self._outcome(value)

    def commit(
        self, value: HandwrittenWord, terminator: str, context: str = ""
    ) -> CommitOutcome:
        self.commit_calls += 1
        return self._outcome(value)

    def commit_cached(
        self,
        value: HandwrittenWord,
        result: RecognitionResult,
        context: str = "",
    ) -> CommitOutcome:
        self.cached_calls += 1
        return CommitOutcome(value, result, result.text, None)


def wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def request_commit(stream: RecognitionStream, value: HandwrittenWord, sequence: int) -> None:
    stream.request_commit(
        value,
        sequence,
        sequence,
        document_id="document",
        line_index=0,
        word_index=sequence - 1,
    )


def test_snapshot_hash_is_stable_and_changes_with_trajectory() -> None:
    original = word()
    same_trajectory = HandwrittenWord(original.strokes)
    assert trajectory_hash(original) == trajectory_hash(same_trajectory)
    assert trajectory_hash(original) != trajectory_hash(word(1.0))


def test_preview_cache_reused_only_for_exact_commit_snapshot() -> None:
    service = FakeStreamingService()
    previews = []
    commits = []
    stream = RecognitionStream(service, on_preview=previews.append, on_commit=commits.append)
    try:
        value = word()
        stream.request_preview(value, 1)
        wait_for(lambda: len(previews) == 1)
        request_commit(stream, word(), 1)
        wait_for(lambda: len(commits) == 1)
        assert commits[0].cache_reused
        assert service.cached_calls == 1
        assert service.commit_calls == 0

        request_commit(stream, word(2.0), 2)
        wait_for(lambda: len(commits) == 2)
        assert not commits[1].cache_reused
        assert service.commit_calls == 1
    finally:
        stream.shutdown(wait=True)


def test_latest_pending_preview_wins_and_stale_result_is_discarded() -> None:
    service = FakeStreamingService()
    service.block_first_preview = True
    previews = []
    stream = RecognitionStream(service, on_preview=previews.append)
    try:
        stream.request_preview(word(), 1)
        assert service.started.wait(timeout=1)
        stream.request_preview(word(1.0), 2)
        stream.request_preview(word(2.0), 3)
        service.release.set()
        wait_for(lambda: len(previews) == 1)
        assert previews[0].request.revision_id == 3
        assert service.preview_calls == 2
        assert stream.snapshot_metrics().stale_preview_discard_count == 1
    finally:
        service.release.set()
        stream.shutdown(wait=True)
