"""Qt thread-pool adapter for non-blocking model inference."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from touchwrite.ink.models import HandwrittenWord
from touchwrite.services.handwriting_service import CommitOutcome, HandwritingService


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class RecognitionWorker(QRunnable):
    def __init__(
        self,
        service: HandwritingService,
        word: HandwrittenWord,
        terminator: str,
        context: str,
    ) -> None:
        super().__init__()
        self.service = service
        self.word = word
        self.terminator = terminator
        self.context = context
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            outcome: CommitOutcome = self.service.commit(
                self.word, self.terminator, self.context
            )
            self.signals.succeeded.emit(outcome)
        except Exception as error:
            self.signals.failed.emit(str(error))

