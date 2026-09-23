from __future__ import annotations

from touchwrite.document.autosave import DocumentAutosave
from touchwrite.document.models import WhiteboardDocument


def test_multiline_document_and_enter_with_reserved_word() -> None:
    document = WhiteboardDocument(document_id="document")
    first = document.reserve_commit(1, " ")
    document.resolve_word(1, "I", "sample-1")
    second = document.reserve_commit(2, "\n")
    document.resolve_word(2, "write", "sample-2")
    third = document.reserve_commit(3, " ")
    document.resolve_word(3, "here", "sample-3")

    assert (first.line_index, second.line_index, third.line_index) == (0, 0, 1)
    assert document.current_line_index == 1
    assert document.to_plain_text() == "I write\nhere "


def test_empty_enter_space_and_current_line_switching() -> None:
    document = WhiteboardDocument()
    assert not document.insert_terminator(" ")
    assert document.insert_terminator("\n")
    assert document.current_line_index == 1
    assert len(document.lines) == 2
    assert document.to_plain_text() == "\n"


def test_out_of_order_results_stay_in_reserved_sequence_slots() -> None:
    document = WhiteboardDocument()
    document.reserve_commit(101, " ")
    document.reserve_commit(102, " ")
    document.resolve_word(102, "world", None)
    assert document.to_plain_text() == ""
    document.resolve_word(101, "hello", None)
    assert document.to_plain_text() == "hello world "


def test_backspace_and_undo_newline() -> None:
    document = WhiteboardDocument()
    document.reserve_commit(1, " ")
    document.resolve_word(1, "hello", None)
    document.insert_terminator("\n")
    assert document.undo() == "newline"
    assert document.current_line_index == 0
    assert document.backspace()
    assert document.to_plain_text() == "hello"
    assert document.backspace()
    assert document.to_plain_text() == ""


def test_autosave_restore_round_trip(tmp_path) -> None:
    path = tmp_path / "documents" / "latest.json"
    autosave = DocumentAutosave(path)
    document = WhiteboardDocument(document_id="saved-document")
    document.reserve_commit(7, "\n")
    document.resolve_word(7, "saved", "sample-7", {"latency": 12.0})
    autosave.save(document)

    restored = autosave.load()
    assert restored is not None
    assert restored.document_id == "saved-document"
    assert restored.current_line_index == 1
    assert restored.to_plain_text() == "saved\n"
