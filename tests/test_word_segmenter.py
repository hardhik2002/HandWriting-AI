from __future__ import annotations

from touchwrite.ink.models import HandwrittenWord, Point, Stroke
from touchwrite.ink.word_segmenter import segment_written_words


def line_stroke(stroke_id: int, min_x: float, max_x: float, timestamp: int) -> Stroke:
    return Stroke(
        stroke_id,
        [
            Point(0.1, 0.2, timestamp, min_x, 10),
            Point(0.2, 0.3, timestamp + 1, max_x, 30),
        ],
    )


def test_clear_horizontal_whitespace_splits_words_not_letters() -> None:
    word = HandwrittenWord(
        [
            line_stroke(1, 10, 30, 1),
            line_stroke(2, 38, 55, 3),
            line_stroke(3, 100, 120, 5),
            line_stroke(4, 128, 145, 7),
        ]
    )
    result = segment_written_words(word)
    assert [[stroke.stroke_id for stroke in item.strokes] for item in result.words] == [
        [1, 2],
        [3, 4],
    ]


def test_small_punctuation_group_attaches_to_previous_word() -> None:
    word = HandwrittenWord(
        [
            line_stroke(1, 10, 35, 1),
            Stroke(2, [Point(0.5, 0.5, 3, 75, 28), Point(0.5, 0.5, 4, 77, 31)]),
            line_stroke(3, 120, 145, 5),
        ]
    )
    result = segment_written_words(word)
    assert [[stroke.stroke_id for stroke in item.strokes] for item in result.words] == [
        [1, 2],
        [3],
    ]

