"""Which bubbles on a straightened page are marked, each judged against its own paper.

OMRChecker's own rule looks for one jump in darkness across every bubble on the
page and, failing that, assumes a fixed grey. Light pencil, or a page lit more
on one side than the other, can hide the jump, and then every empty bubble
darker than that grey reads as marked. Here each bubble is compared only with
the paper right around it: its darkness over the paper's brightness. Uneven
light dims both alike, so the comparison holds across the page.

On real phone photos filled bubbles come to 0.46-0.56 of their paper and empty
ones (a printed ring around white) to 0.71 and over. In between, a bubble is
left for a person to check; a page with many in between (a sheet straightened
wrongly, or marks too faint to tell) isn't read at all.

Some scanners make every mark lighter: a scanner's PDF came to 0.55-0.64 for
its marks, and slashed or scribbled marks fell in between, though the page's
empty bubbles were all over 0.73. So each page also looks for its own gap: when
one gap, clearly wider than any other, parts the in-between bubbles from the
marks or from the empty ones, they're read by which side they're on. They're
still left for a person to check, but no longer make the page unreadable.

Empty bubbles are much alike on any one page, at a level each scanner or
camera sets: 0.72-0.83 in phone photos, 0.80-0.85 in that scanner's PDF, where
light scribbles came to 0.69-0.75, past EMPTY_ABOVE. So a bubble well darker
than the page's typical empty bubble (its median: most bubbles are empty) is
never taken as empty: it's left for a person to check.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from statistics import median
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from omr_data_collector.engine.runner import MeasuredBubble, MeasuredPage

# Darkness over the paper's brightness: below this a bubble is marked, above
# EMPTY_ABOVE it is empty, and in between it can't be told.
MARKED_BELOW = 0.60
EMPTY_ABOVE = 0.68
# The paper around a bubble: what's in a margin as wide as the bubble on every
# side, taken at this percentile so print and marks nearby don't count.
PAPER_PERCENTILE = 90
# More bubbles than this that can't be told, and more than this share of the
# page's, and the page isn't read.
MOST_UNCLEAR = 3
MOST_UNCLEAR_SHARE = 0.02
# A page's own gap between its marks and its empty bubbles: at least this
# wide, and this many times as wide as any other gap among the bubbles in
# between, so a bubble halfway between the two is still unclear.
MIN_PAGE_GAP = 0.06
PAGE_GAP_LEAD = 2.0
# Darker than the page's typical empty bubble by more than this, and a bubble
# isn't clearly empty. Taken only on pages with at least EMPTY_LEVEL_BUBBLES
# bubbles, where the median is surely an empty one.
EMPTY_MARGIN = 0.06
EMPTY_LEVEL_BUBBLES = 20


class MarksUnclearError(Exception):
    """Too many of a page's bubbles are neither clearly marked nor clearly empty."""


@dataclass(frozen=True)
class FieldMarks:
    """One template field's bubbles: which are marked, and whether any is unclear.

    ``marked`` are bubble indices in the field, left to right.
    """

    marked: tuple[int, ...] = ()
    unclear: bool = False


def darkness(page: MeasuredPage, bubble: MeasuredBubble) -> float:
    """``bubble``'s mean grey over the brightness of the paper around it."""
    x, y, width, height = bubble.rect
    margin = max(width, height)
    around = page.image[
        max(0, y - margin) : y + height + margin,
        max(0, x - margin) : x + width + margin,
    ]
    paper = float(np.percentile(around, PAPER_PERCENTILE)) if around.size else 0.0
    return bubble.mean / paper if paper > 0 else 1.0


def read_marks(page: MeasuredPage) -> dict[str, FieldMarks]:
    """Each field's marked bubbles, by field label.

    Raises:
        MarksUnclearError: Too many bubbles are neither clearly marked nor
            clearly empty to trust the page.
    """
    ratios = [(bubble, darkness(page, bubble)) for bubble in page.bubbles]
    values = [ratio for _, ratio in ratios]
    split = page_split(values)
    darker_than_empty = (
        median(values) - EMPTY_MARGIN
        if len(values) >= EMPTY_LEVEL_BUBBLES
        else EMPTY_ABOVE
    )
    marked: dict[str, list[int]] = {}
    unclear: set[str] = set()
    unclear_bubbles = 0
    for bubble, ratio in ratios:
        marked.setdefault(bubble.field_label, [])
        in_between = MARKED_BELOW <= ratio <= EMPTY_ABOVE
        if in_between or EMPTY_ABOVE < ratio < darker_than_empty:
            unclear.add(bubble.field_label)
        if ratio < (MARKED_BELOW if split is None else min(split, darker_than_empty)):
            marked[bubble.field_label].append(bubble.index)
        elif in_between and split is None:
            unclear_bubbles += 1
    if unclear_bubbles > max(MOST_UNCLEAR, MOST_UNCLEAR_SHARE * len(page.bubbles)):
        msg = f"{unclear_bubbles} of {len(page.bubbles)} bubbles unclear"
        raise MarksUnclearError(msg)
    return {
        label: FieldMarks(marked=tuple(sorted(indices)), unclear=label in unclear)
        for label, indices in marked.items()
    }


def page_split(ratios: list[float]) -> float | None:
    """Where this page's marks end and its empty bubbles begin, if it's clear.

    Looked for only among the bubbles in between, and from the lightest mark
    to the darkest empty bubble beside them: the middle of the widest gap,
    when it's at least MIN_PAGE_GAP and PAGE_GAP_LEAD times any other there.
    None when there's nothing in between, no marks or no empty bubbles, or no
    gap stands out.
    """
    marks = [ratio for ratio in ratios if ratio < MARKED_BELOW]
    empty = [ratio for ratio in ratios if ratio > EMPTY_ABOVE]
    between = [ratio for ratio in ratios if MARKED_BELOW <= ratio <= EMPTY_ABOVE]
    if not (marks and empty and between):
        return None
    values = sorted([max(marks), *between, min(empty)])
    gaps = sorted(
        ((upper - lower, lower, upper) for lower, upper in pairwise(values)),
        reverse=True,
    )
    widest, lower, upper = gaps[0]
    runner_up = gaps[1][0] if len(gaps) > 1 else 0.0
    if widest < MIN_PAGE_GAP or widest < PAGE_GAP_LEAD * runner_up:
        return None
    return (lower + upper) / 2
