"""Bubbles judged against the paper around them (engine/marks.py)."""

from __future__ import annotations

import numpy as np
import pytest

from omr_data_collector.engine.marks import (
    FieldMarks,
    MarksUnclearError,
    darkness,
    read_marks,
)
from omr_data_collector.engine.runner import MeasuredBubble, MeasuredPage

SIZE = 10
GAP = 40


def page_of(rows: list[tuple[str, list[float]]], paper: list[int]) -> MeasuredPage:
    """Fields of bubbles with these means, one field per row, on paper this bright.

    ``paper`` is each column's brightness, left to right, so light can fall off
    across the page.
    """
    width = GAP * len(paper)
    image = np.zeros((GAP * len(rows), width), dtype=np.uint8)
    for column, brightness in enumerate(paper):
        image[:, column * GAP : (column + 1) * GAP] = brightness
    bubbles = tuple(
        MeasuredBubble(
            field_label=label,
            index=index,
            mean=mean,
            rect=(index * GAP + 15, row * GAP + 15, SIZE, SIZE),
        )
        for row, (label, means) in enumerate(rows)
        for index, mean in enumerate(means)
    )
    return MeasuredPage(image=image, bubbles=bubbles)


def test_darkness_is_against_the_paper_around_the_bubble() -> None:
    page = page_of([("a", [100.0, 100.0])], paper=[250, 125])

    assert darkness(page, page.bubbles[0]) == pytest.approx(0.4)
    assert darkness(page, page.bubbles[1]) == pytest.approx(0.8)


def test_the_same_grey_is_marked_in_good_light_and_empty_in_poor() -> None:
    # A lamp off to the left: paper at 250 there, 150 on the right.
    page = page_of(
        [("a", [120.0, 190.0, 115.0]), ("b", [195.0, 125.0, 112.0])],
        paper=[250, 240, 150],
    )

    assert read_marks(page) == {
        "a": FieldMarks(marked=(0,)),
        "b": FieldMarks(marked=(1,)),
    }


def test_a_bubble_in_between_is_unclear_and_not_marked() -> None:
    page = page_of([("a", [100.0, 160.0, 220.0])], paper=[250, 250, 250])

    assert read_marks(page) == {"a": FieldMarks(marked=(0,), unclear=True)}


def test_a_page_with_many_unclear_bubbles_isnt_trusted() -> None:
    rows = [(f"f{row}", [160.0, 220.0, 220.0]) for row in range(4)]

    with pytest.raises(MarksUnclearError):
        read_marks(page_of(rows, paper=[250, 250, 250]))


def test_a_phone_photo_that_misread_page_wide_reads_bubble_by_bubble() -> None:
    # Measured from a real photo that OMRChecker's page-wide rule misread:
    # marks 113-133 and empty bubbles 150-191, with the paper darker towards
    # the right. No single grey parts them, so it called every empty bubble
    # marked; against their own paper they're far apart.
    page = page_of(
        [
            ("a", [120.0, 178.0, 150.0]),
            ("b", [191.0, 133.0, 152.0]),
            ("c", [189.0, 176.0, 113.0]),
        ],
        paper=[250, 235, 205],
    )

    assert read_marks(page) == {
        "a": FieldMarks(marked=(0,)),
        "b": FieldMarks(marked=(1,)),
        "c": FieldMarks(marked=(2,)),
    }


def page_of_ratios(ratios: list[float]) -> MeasuredPage:
    """One bubble per field, each this dark against white paper."""
    return page_of(
        [(f"f{row}", [250.0 * ratio]) for row, ratio in enumerate(ratios)], paper=[250]
    )


# A scanner's PDF that came out lighter than phone photos: its empty bubbles
# at 0.80-0.85, its marks at 0.5 and, slashed or scribbled, lighter.
SCANNED_EMPTY = [0.80, 0.81, 0.82, 0.82, 0.83, 0.84, 0.85] * 3


def test_light_marks_a_clear_gap_parts_from_the_empty_ones_are_read() -> None:
    light = [0.62, 0.63, 0.64, 0.645]
    page = page_of_ratios([0.50, 0.52, 0.55, *light, *SCANNED_EMPTY])

    read = read_marks(page)

    # Four in between once made the page unreadable; now they're read as
    # marked, and still left for a person to check.
    for row in range(3):
        assert read[f"f{row}"] == FieldMarks(marked=(0,))
    for row in range(3, 7):
        assert read[f"f{row}"] == FieldMarks(marked=(0,), unclear=True)
    assert all(read[f"f{row}"] == FieldMarks() for row in range(7, 28))


def test_marks_in_between_with_no_clear_gap_still_make_the_page_unreadable() -> None:
    # Evenly spread from the marks to the empty bubbles: nothing parts them.
    page = page_of_ratios([0.50, 0.55, 0.60, 0.63, 0.66, 0.68, 0.72, *SCANNED_EMPTY])

    with pytest.raises(MarksUnclearError):
        read_marks(page)


def test_a_light_mark_past_the_band_is_checked_when_the_empty_ones_are_lighter() -> (
    None
):
    # 0.72 would be empty in a phone photo, but on this page every empty
    # bubble is 0.80 or more: it's a light mark, or something on the paper.
    page = page_of_ratios([0.50, 0.72, *SCANNED_EMPTY])

    read = read_marks(page)

    assert read["f0"] == FieldMarks(marked=(0,))
    assert read["f1"] == FieldMarks(unclear=True)
    assert all(not marks.unclear for label, marks in read.items() if label != "f1")


def test_a_phone_photos_empty_bubbles_arent_checked() -> None:
    # Measured from real phone photos: empty bubbles at 0.71-0.83, around 0.75.
    phone_empty = [0.71, 0.72, 0.73, 0.74, 0.75, 0.75, 0.76, 0.77, 0.79, 0.83] * 2

    read = read_marks(page_of_ratios([0.47, 0.53, 0.56, *phone_empty]))

    assert not any(marks.unclear for marks in read.values())
    assert [label for label, marks in read.items() if marks.marked] == [
        "f0",
        "f1",
        "f2",
    ]
