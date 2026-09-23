"""Ordered, serializable multi-line whiteboard document state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class DocumentWord:
    commit_sequence_id: int
    text: str | None = None
    source_sample_id: str | None = None
    recognition_metadata: dict[str, Any] = field(default_factory=dict)
    failed: bool = False

    @property
    def display_text(self) -> str:
        if self.failed:
            return "[recognition failed]"
        return self.text if self.text is not None else "…"


@dataclass(slots=True)
class DocumentLine:
    words: list[DocumentWord] = field(default_factory=list)
    trailing_space: bool = False

    def text(self, *, include_pending: bool = False) -> str:
        values: list[str] = []
        for word in self.words:
            if word.text is None:
                if not include_pending:
                    break
                values.append("…")
            else:
                values.append(word.text)
        text = " ".join(values)
        return text + (" " if self.trailing_space and text else "")


@dataclass(frozen=True, slots=True)
class WordSlot:
    document_id: str
    line_index: int
    word_index: int
    commit_sequence_id: int


@dataclass(slots=True)
class _HistoryEntry:
    label: str
    state: dict[str, Any]


class WhiteboardDocument:
    """Document state whose pending slots make async recognition ordering deterministic."""

    VERSION = 1

    def __init__(
        self,
        *,
        document_id: str | None = None,
        lines: list[DocumentLine] | None = None,
        current_line_index: int = 0,
    ) -> None:
        self.document_id = document_id or str(uuid4())
        self.lines = lines or [DocumentLine()]
        self.current_line_index = min(max(current_line_index, 0), len(self.lines) - 1)
        self._undo: list[_HistoryEntry] = []
        self._redo: list[_HistoryEntry] = []

    @property
    def current_line(self) -> DocumentLine:
        return self.lines[self.current_line_index]

    def reserve_commit(self, commit_sequence_id: int, terminator: str) -> WordSlot:
        self._remember(f"commit:{commit_sequence_id}")
        line_index = self.current_line_index
        line = self.current_line
        line.trailing_space = False
        word_index = len(line.words)
        line.words.append(DocumentWord(commit_sequence_id))
        slot = WordSlot(self.document_id, line_index, word_index, commit_sequence_id)
        if terminator == "\n":
            self._insert_newline()
        elif terminator == " ":
            line.trailing_space = True
        return slot

    def insert_terminator(self, terminator: str) -> bool:
        if terminator == "\n":
            self._remember("newline")
            self._insert_newline()
            return True
        if terminator == " " and self.current_line.words and not self.current_line.trailing_space:
            self._remember("space")
            self.current_line.trailing_space = True
            return True
        return False

    def resolve_word(
        self,
        commit_sequence_id: int,
        text: str,
        source_sample_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        word = self._find_word(commit_sequence_id)
        if word is None:
            return False
        word.text = text
        word.source_sample_id = source_sample_id
        word.recognition_metadata = dict(metadata or {})
        word.failed = False
        return True

    def fail_word(self, commit_sequence_id: int) -> bool:
        word = self._find_word(commit_sequence_id)
        if word is None:
            return False
        word.failed = True
        return True

    def remove_pending(self, commit_sequence_id: int) -> bool:
        for line in self.lines:
            for index, word in enumerate(line.words):
                if word.commit_sequence_id == commit_sequence_id and word.text is None:
                    line.words.pop(index)
                    if not line.words:
                        line.trailing_space = False
                    return True
        return False

    def backspace(self) -> bool:
        line = self.current_line
        if line.trailing_space:
            self._remember("backspace-space")
            line.trailing_space = False
            return True
        if line.words:
            self._remember("backspace-word")
            line.words.pop()
            return True
        if self.current_line_index == 0:
            return False
        self._remember("backspace-newline")
        removed = self.lines.pop(self.current_line_index)
        self.current_line_index -= 1
        previous = self.current_line
        previous.trailing_space = False
        previous.words.extend(removed.words)
        return True

    def clear(self) -> None:
        self._remember("clear-document")
        self.lines = [DocumentLine()]
        self.current_line_index = 0

    def new_document(self) -> None:
        self._remember("new-document")
        self.document_id = str(uuid4())
        self.lines = [DocumentLine()]
        self.current_line_index = 0

    def undo(self) -> str | None:
        if not self._undo:
            return None
        entry = self._undo.pop()
        self._redo.append(_HistoryEntry(entry.label, self.to_dict(include_history=False)))
        self._restore_state(entry.state)
        return entry.label

    def redo(self) -> str | None:
        if not self._redo:
            return None
        entry = self._redo.pop()
        self._undo.append(_HistoryEntry(entry.label, self.to_dict(include_history=False)))
        self._restore_state(entry.state)
        return entry.label

    def to_plain_text(self, *, include_pending: bool = False) -> str:
        return "\n".join(line.text(include_pending=include_pending) for line in self.lines)

    def to_dict(self, *, include_history: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {
            "version": self.VERSION,
            "document_id": self.document_id,
            "current_line_index": self.current_line_index,
            "lines": [asdict(line) for line in self.lines],
        }
        if include_history:
            value["undo"] = [asdict(entry) for entry in self._undo]
            value["redo"] = [asdict(entry) for entry in self._redo]
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> WhiteboardDocument:
        lines = [
            DocumentLine(
                words=[DocumentWord(**word) for word in line.get("words", [])],
                trailing_space=bool(line.get("trailing_space", False)),
            )
            for line in value.get("lines", [])
        ]
        document = cls(
            document_id=str(value.get("document_id") or uuid4()),
            lines=lines or [DocumentLine()],
            current_line_index=int(value.get("current_line_index", 0)),
        )
        document._undo = [
            _HistoryEntry(str(item["label"]), dict(item["state"]))
            for item in value.get("undo", [])
        ]
        document._redo = [
            _HistoryEntry(str(item["label"]), dict(item["state"]))
            for item in value.get("redo", [])
        ]
        return document

    def _insert_newline(self) -> None:
        self.current_line.trailing_space = False
        self.current_line_index += 1
        self.lines.insert(self.current_line_index, DocumentLine())

    def _find_word(self, commit_sequence_id: int) -> DocumentWord | None:
        return next(
            (
                word
                for line in self.lines
                for word in line.words
                if word.commit_sequence_id == commit_sequence_id
            ),
            None,
        )

    def _remember(self, label: str) -> None:
        self._undo.append(_HistoryEntry(label, self.to_dict(include_history=False)))
        self._redo.clear()

    def _restore_state(self, value: dict[str, Any]) -> None:
        restored = self.from_dict(value)
        self.document_id = restored.document_id
        self.lines = restored.lines
        self.current_line_index = restored.current_line_index
