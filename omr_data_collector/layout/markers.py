"""The registration markers printed in each page corner.

OMRChecker finds these four markers in a photo or scan and straightens the page
on them, so every bubble lands where the template expects it. They sit in the
page margin, clear of everything else, as round targets: unlike the QR code's
square corner patterns, and too big to be mistaken for a filled-in bubble.
"""

from __future__ import annotations

from omr_data_collector.layout.page_setup import PAGE_MARGIN_MM

MARKER_DIAMETER_MM = 6.0
# Drawn as a target: a black ring, a white ring, then a black centre. Easy to
# aim a camera at, and unlike anything else printed on the page.
MARKER_WHITE_RING_DIAMETER_MM = 4.0
MARKER_CENTRE_DIAMETER_MM = 2.2


def marker_rings_mm() -> tuple[tuple[float, bool], ...]:
    """The marker's discs from the outside in: (diameter, black?)."""
    return (
        (MARKER_DIAMETER_MM, True),
        (MARKER_WHITE_RING_DIAMETER_MM, False),
        (MARKER_CENTRE_DIAMETER_MM, True),
    )


# Centre of each marker from the two nearest paper edges: inside what office
# printers can print (about 5 mm from the edge), and outside the printable area
# the form's content uses.
MARKER_INSET_MM = 8.5


def marker_centres_mm(
    paper_width_mm: float, paper_height_mm: float
) -> tuple[tuple[float, float], ...]:
    """The four marker centres, top-left first, clockwise.

    Relative to the top-left of the printable area, like the rest of the layout,
    so the top-left marker is up and left of the origin (negative coordinates).
    """
    left = top = MARKER_INSET_MM - PAGE_MARGIN_MM
    right = paper_width_mm - MARKER_INSET_MM - PAGE_MARGIN_MM
    bottom = paper_height_mm - MARKER_INSET_MM - PAGE_MARGIN_MM
    return ((left, top), (right, top), (right, bottom), (left, bottom))
