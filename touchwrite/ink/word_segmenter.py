"""Conservative whitespace segmentation for buffers containing multiple written words."""

from __future__ import annotations

from dataclasses import dataclass

from touchwrite.ink.models import HandwrittenWord, Stroke
from touchwrite.ink.renderer import bounding_box, stroke_path_length


@dataclass(frozen=True, slots=True)
class SegmentationResult:
    words: tuple[HandwrittenWord, ...]
    gap_threshold: float
    boundary_gaps: tuple[float, ...]


def segment_written_words(word: HandwrittenWord) -> SegmentationResult:
    """Split clear horizontal whitespace while keeping dots/crosses with overlapping ink."""
    bounds = bounding_box(word.strokes)
    if bounds is None or len(word.strokes) < 2:
        return SegmentationResult((word,), 0.0, ())
    ink_height = max(1.0, bounds.max_y - bounds.min_y)
    threshold = max(28.0, ink_height * 0.4)
    ordered = sorted(
        word.strokes,
        key=lambda stroke: (
            bounding_box([stroke]).min_x if bounding_box([stroke]) is not None else 0.0,
            stroke.start_time_ns or 0,
        ),
    )
    groups: list[list[Stroke]] = []
    gaps: list[float] = []
    for stroke in ordered:
        stroke_bounds = bounding_box([stroke])
        if stroke_bounds is None:
            continue
        if not groups:
            groups.append([stroke])
            continue
        group_bounds = bounding_box(groups[-1])
        if group_bounds is None:
            groups[-1].append(stroke)
            continue
        gap = stroke_bounds.min_x - group_bounds.max_x
        if gap > threshold:
            groups.append([stroke])
            gaps.append(gap)
        else:
            groups[-1].append(stroke)
    groups = _attach_punctuation_groups(groups, ink_height)
    words = tuple(
        HandwrittenWord(
            strokes=sorted(group, key=lambda stroke: stroke.start_time_ns or 0),
            recognition_metadata={**word.recognition_metadata, "source_word_id": word.word_id},
        )
        for group in groups
    )
    return SegmentationResult(words or (word,), threshold, tuple(gaps))


def _attach_punctuation_groups(groups: list[list[Stroke]], ink_height: float) -> list[list[Stroke]]:
    output: list[list[Stroke]] = []
    for group in groups:
        bounds = bounding_box(group)
        total_path = sum(stroke_path_length(stroke) for stroke in group)
        is_small_mark = (
            bounds is not None
            and bounds.max_x - bounds.min_x < ink_height * 0.35
            and total_path < ink_height * 0.65
        )
        if is_small_mark and output:
            output[-1].extend(group)
        else:
            output.append(group)
    return output

