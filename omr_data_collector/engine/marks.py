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
"""

from __future__ import annotations

from dataclasses import dataclass
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
    marked: dict[str, list[int]] = {}
    unclear: set[str] = set()
    unclear_bubbles = 0
    for bubble in page.bubbles:
        ratio = darkness(page, bubble)
        marked.setdefault(bubble.field_label, [])
        if ratio < MARKED_BELOW:
            marked[bubble.field_label].append(bubble.index)
        elif ratio <= EMPTY_ABOVE:
            unclear.add(bubble.field_label)
            unclear_bubbles += 1
    if unclear_bubbles > max(MOST_UNCLEAR, MOST_UNCLEAR_SHARE * len(page.bubbles)):
        msg = f"{unclear_bubbles} of {len(page.bubbles)} bubbles unclear"
        raise MarksUnclearError(msg)
    return {
        label: FieldMarks(marked=tuple(sorted(indices)), unclear=label in unclear)
        for label, indices in marked.items()
    }
