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
