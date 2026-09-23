"""Single-worker, latest-wins streaming recognition orchestration."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal

from touchwrite.ink.models import HandwrittenWord
from touchwrite.services.handwriting_service import CommitOutcome, HandwritingService


def trajectory_hash(word: HandwrittenWord) -> str:
    """Hash recognition trajectory content, excluding display-only coordinates."""
    trajectory = [
        {
            "stroke_id": stroke.stroke_id,
            "points": [
                {
                    "x": point.x,
                    "y": point.y,
                    "timestamp_ns": point.timestamp_ns,
                    "x_raw": point.x_raw,
                    "y_raw": point.y_raw,
                    "pressure": point.pressure,
                    "contact_id": point.contact_id,
                    "finger_down": point.finger_down,
                    "dx": point.dx,
                    "dy": point.dy,
                    "velocity": point.velocity,
                }
                for point in stroke.points
            ],
        }
        for stroke in word.strokes
    ]
    payload = json.dumps(
        trajectory,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class RecognitionRequest:
    kind: Literal["preview", "commit"]
    word: HandwrittenWord
    fingerprint: str
    revision_id: int
    context: str = ""
    commit_sequence_id: int | None = None
    document_id: str | None = None
    line_index: int | None = None
    word_index: int | None = None


@dataclass(frozen=True, slots=True)
class RecognitionEvent:
    request: RecognitionRequest
    outcome: CommitOutcome
    cache_reused: bool = False


@dataclass(frozen=True, slots=True)
class RecognitionFailure:
    request: RecognitionRequest
    message: str


@dataclass(slots=True)
class StreamMetrics:
    preview_scheduling_delay_ms: float = 0.0
    preview_inference_ms: float = 0.0
    commit_inference_ms: float = 0.0
    cache_reuse_count: int = 0
    stale_preview_discard_count: int = 0
    model_load_count: int = 0
    completed_previews: int = 0
    completed_commits: int = 0
    pointer_to_ink_latency_ms: float = 0.0

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _CachedRecognition:
    outcome: CommitOutcome


class RecognitionStream:
    """Run exactly one model call at a time and coalesce pending preview work."""

    def __init__(
        self,
        service: HandwritingService,
        *,
        on_preview: Callable[[RecognitionEvent], None] | None = None,
        on_commit: Callable[[RecognitionEvent], None] | None = None,
        on_failure: Callable[[RecognitionFailure], None] | None = None,
        cache_size: int = 128,
    ) -> None:
        self.service = service
        self.on_preview = on_preview or (lambda _event: None)
        self.on_commit = on_commit or (lambda _event: None)
        self.on_failure = on_failure or (lambda _failure: None)
        self.cache_size = cache_size
        self.metrics = StreamMetrics()
        self._condition = threading.Condition()
        self._commit_queue: deque[RecognitionRequest] = deque()
        self._pending_preview: RecognitionRequest | None = None
        self._current_revision_id = 0
        self._cache: OrderedDict[str, _CachedRecognition] = OrderedDict()
        self._stopping = False
        self._model_load_observed = False
        self._thread = threading.Thread(
            target=self._run, name="touchwrite-recognition", daemon=True
        )
        self._thread.start()

    def set_current_revision(self, revision_id: int) -> None:
        with self._condition:
            self._current_revision_id = revision_id

    def request_preview(
        self,
        word: HandwrittenWord,
        revision_id: int,
        context: str = "",
        *,
        scheduled_at: float | None = None,
    ) -> str:
        fingerprint = trajectory_hash(word)
        request = RecognitionRequest("preview", word, fingerprint, revision_id, context)
        with self._condition:
            if self._stopping:
                return fingerprint
            self._current_revision_id = max(self._current_revision_id, revision_id)
            self._pending_preview = request
            if scheduled_at is not None:
                self.metrics.preview_scheduling_delay_ms = max(
                    0.0, (time.perf_counter() - scheduled_at) * 1000
                )
            self._condition.notify()
        return fingerprint

    def request_commit(
        self,
        word: HandwrittenWord,
        revision_id: int,
        commit_sequence_id: int,
        *,
        context: str = "",
        document_id: str,
        line_index: int,
        word_index: int,
    ) -> str:
        fingerprint = trajectory_hash(word)
        request = RecognitionRequest(
            "commit",
            word,
            fingerprint,
            revision_id,
            context,
            commit_sequence_id,
            document_id,
            line_index,
            word_index,
        )
        with self._condition:
            if self._stopping:
                return fingerprint
            self._commit_queue.append(request)
            self._condition.notify()
        return fingerprint

    def snapshot_metrics(self) -> StreamMetrics:
        with self._condition:
            return StreamMetrics(**self.metrics.to_dict())

    def pending_commit_count(self) -> int:
        with self._condition:
            return len(self._commit_queue)

    def shutdown(self, *, wait: bool = False) -> None:
        with self._condition:
            self._stopping = True
            self._pending_preview = None
            self._condition.notify_all()
        if wait:
            self._thread.join()

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._stopping
                    or bool(self._commit_queue)
                    or self._pending_preview is not None
                )
                if self._stopping:
                    return
                if self._commit_queue:
                    request = self._commit_queue.popleft()
                else:
                    request, self._pending_preview = self._pending_preview, None
            if request is not None:
                self._execute(request)

    def _execute(self, request: RecognitionRequest) -> None:
        cached = self._cache.get(request.fingerprint)
        started = time.perf_counter()
        try:
            if request.kind == "commit":
                self._apply_commit_metadata(request)
                if cached is not None:
                    outcome = self.service.commit_cached(
                        request.word, cached.outcome.result, request.context
                    )
                    cache_reused = True
                else:
                    outcome = self.service.commit(request.word, "", request.context)
                    cache_reused = False
                elapsed = (time.perf_counter() - started) * 1000
                with self._condition:
                    self.metrics.commit_inference_ms = elapsed
                    self.metrics.completed_commits += 1
                    self.metrics.cache_reuse_count += int(cache_reused)
                    self._observe_model_load(outcome)
                self._put_cache(request.fingerprint, outcome)
                self.on_commit(RecognitionEvent(request, outcome, cache_reused))
                return

            if cached is not None:
                outcome = cached.outcome
            else:
                outcome = self.service.preview(request.word, request.context)
                self._put_cache(request.fingerprint, outcome)
            elapsed = (time.perf_counter() - started) * 1000
            with self._condition:
                self.metrics.preview_inference_ms = elapsed
                self.metrics.completed_previews += 1
                self._observe_model_load(outcome)
                stale = request.revision_id != self._current_revision_id
                if stale:
                    self.metrics.stale_preview_discard_count += 1
            if not stale:
                self.on_preview(RecognitionEvent(request, outcome, cached is not None))
        except Exception as error:  # worker boundary: report recoverable failures to the UI
            self.on_failure(RecognitionFailure(request, str(error)))

    def _apply_commit_metadata(self, request: RecognitionRequest) -> None:
        request.word.document_id = request.document_id
        request.word.line_index = request.line_index
        request.word.word_index = request.word_index
        request.word.commit_sequence_id = request.commit_sequence_id
        request.word.recognition_metadata = {
            **request.word.recognition_metadata,
            "trajectory_hash": request.fingerprint,
            "revision_id": request.revision_id,
        }

    def _put_cache(self, fingerprint: str, outcome: CommitOutcome) -> None:
        self._cache[fingerprint] = _CachedRecognition(outcome)
        self._cache.move_to_end(fingerprint)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    def _observe_model_load(self, outcome: CommitOutcome) -> None:
        if outcome.result.model_load_duration_ms is not None and not self._model_load_observed:
            self.metrics.model_load_count = 1
            self._model_load_observed = True
