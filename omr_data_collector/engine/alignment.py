"""Where a page's QR code is, and what that says about how the page lies.

The form QR code is printed at a known place and size in every page's top-right
corner, and the reader reports its corners in the code's own order (top-left,
top-right, bottom-right, bottom-left), however the picture is turned. That
gives three things the corner markers alone can't:

- which way up the page was photographed, so it can be turned upright;
- a check after straightening: the code must land where the form put it, or
  the page was lined up wrongly and its bubbles would be read in the wrong
  places;
- a rough frame for a page printed at another size (a landscape form shrunk
  onto portrait paper, say), so its markers can be found anyway.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from omr_data_collector.identity.qr_code import (
    QR_BORDER_MODULES,
    build_form_payload,
    make_qr_code,
)
from omr_data_collector.layout.form_layout import QR_SIZE_MM
from omr_data_collector.layout.markers import MARKER_INSET_MM
from omr_data_collector.layout.omr_template import TEMPLATE_PX_PER_MM
from omr_data_collector.layout.page_setup import PAGE_MARGIN_MM

if TYPE_CHECKING:
    from omr_data_collector.engine.scanning import SheetIdentity

# How far the code's centre may land from where the form put it, after
# straightening. Generous, since sheets printed before 2026-10-10 have a 22 mm
# code (its centre 2 mm from today's 26 mm one), but far less than any page
# lined up the wrong way round or stretched out of shape.
ALIGNMENT_TOLERANCE_MM = 6.0
# How far from level the code's top edge may be once straightened.
ALIGNMENT_TOLERANCE_DEGREES = 20.0
# The straightened code's size against the expected one (22 mm codes are 0.85).
ALIGNMENT_SIZE_RANGE = (0.7, 1.3)
# A re-framed picture is drawn at this many pixels per millimetre of paper: as
# sharp as the tests' photos, and plenty for finding the markers.
REFRAME_PX_PER_MM = 8.0
# Paper's worth of white added on every side of a re-framed picture, as a share
# of the paper's size: a slightly tilted or skewed photo then keeps its markers
# in the picture. The same share on both sides keeps the paper's proportions,
# which straightening scales the picture to.
REFRAME_MARGIN = 0.08


@dataclass(frozen=True)
class PaperFrame:
    """A printed page's paper size, from its stored OMR template."""

    width_mm: float
    height_mm: float

    @classmethod
    def from_template(cls, template: dict[str, Any]) -> PaperFrame:
        # The template spans the marker centres, each MARKER_INSET_MM in from
        # the paper's edges.
        width_px, height_px = template["templateDimensions"]
        return cls(
            width_mm=width_px / TEMPLATE_PX_PER_MM + 2 * MARKER_INSET_MM,
            height_mm=height_px / TEMPLATE_PX_PER_MM + 2 * MARKER_INSET_MM,
        )

    def code_corners_mm(self, identity: SheetIdentity) -> np.ndarray:
        """The printed code's corners (quiet zone excluded), in mm from the paper's corner.

        Top-left first, clockwise, as the QR reader reports them.
        """
        modules = make_qr_code(
            build_form_payload(
                identity.organization_id,
                identity.form_id,
                identity.form_version,
                identity.page,
            )
        ).symbol_size(border=0)[0]
        module_mm = QR_SIZE_MM / (modules + 2 * QR_BORDER_MODULES)
        left = self.width_mm - PAGE_MARGIN_MM - QR_SIZE_MM
        left += QR_BORDER_MODULES * module_mm
        top = PAGE_MARGIN_MM + QR_BORDER_MODULES * module_mm
        size = modules * module_mm
        return np.array(
            [
                (left, top),
                (left + size, top),
                (left + size, top + size),
                (left, top + size),
            ],
            dtype=np.float64,
        )

    def code_corners_template_px(self, identity: SheetIdentity) -> np.ndarray:
        """The same corners in template pixels (from the top-left marker's centre)."""
        return (self.code_corners_mm(identity) - MARKER_INSET_MM) * TEMPLATE_PX_PER_MM


def quarter_turns(corners: np.ndarray) -> int:
    """How many quarter turns clockwise the page lies from upright (0 to 3).

    From the direction of the code's top edge: rightwards when upright,
    downwards when the page lies turned a quarter clockwise, and so on.
    """
    dx, dy = corners[1] - corners[0]
    return round(math.degrees(math.atan2(dy, dx)) / 90) % 4


def turn_upright(
    image: np.ndarray, corners: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Turn a picture so its page is upright; the code's corners move with it."""
    turns = quarter_turns(corners)
    if turns == 0:
        return image, corners
    height, width = image.shape[:2]
    x, y = corners[:, 0], corners[:, 1]
    if turns == 1:
        turned = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        moved = np.column_stack((y, width - 1 - x))
    elif turns == 2:
        turned = cv2.rotate(image, cv2.ROTATE_180)
        moved = np.column_stack((width - 1 - x, height - 1 - y))
    else:
        turned = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        moved = np.column_stack((height - 1 - y, x))
    return turned, moved


def misalignment(corners: np.ndarray | None, expected: np.ndarray) -> str | None:
    """Why a straightened page's code isn't where the form put it; None if it is.

    ``corners`` are the code's corners found on the straightened page (None if
    it wasn't found there), ``expected`` where the form puts them, both in
    template pixels. The reason is for the log, not for people.
    """
    if corners is None:
        return "code not found on the straightened page"
    centre_mm = np.linalg.norm(corners.mean(axis=0) - expected.mean(axis=0))
    centre_mm /= TEMPLATE_PX_PER_MM
    if centre_mm > ALIGNMENT_TOLERANCE_MM:
        return f"code {centre_mm:.1f} mm from where the form puts it"
    dx, dy = corners[1] - corners[0]
    tilt = abs(math.degrees(math.atan2(dy, dx)))
    if tilt > ALIGNMENT_TOLERANCE_DEGREES:
        return f"code turned {tilt:.0f} degrees"
    size = _side(corners) / _side(expected)
    low, high = ALIGNMENT_SIZE_RANGE
    if not low <= size <= high:
        return f"code {size:.2f} times its printed size"
    return None


def _side(corners: np.ndarray) -> float:
    """The code's mean side length."""
    return float(
        np.mean(
            [
                np.linalg.norm(corners[(index + 1) % 4] - corners[index])
                for index in range(4)
            ]
        )
    )


def reframed(
    image: np.ndarray,
    corners: np.ndarray,
    frame: PaperFrame,
    identity: SheetIdentity,
) -> np.ndarray:
    """Redraw an upright picture as the paper the form was laid out on, from its code.

    Moves, turns and scales the picture (no stretching or skewing) so the code
    lands where the form puts it, at ``REFRAME_PX_PER_MM``; whatever falls
    outside the picture is white paper, with ``REFRAME_MARGIN`` around it. A page printed smaller or larger than
    laid out then has its markers about where the template expects them, and
    straightening on them corrects what's left.
    """
    margin = np.array([frame.width_mm, frame.height_mm]) * REFRAME_MARGIN
    expected = (frame.code_corners_mm(identity) + margin) * REFRAME_PX_PER_MM
    transform, _ = cv2.estimateAffinePartial2D(
        corners.astype(np.float32), expected.astype(np.float32)
    )
    scale = REFRAME_PX_PER_MM * (1 + 2 * REFRAME_MARGIN)
    size = (round(frame.width_mm * scale), round(frame.height_mm * scale))
    white = (255, 255, 255) if image.ndim == 3 else 255
    return cv2.warpAffine(
        image,
        transform,
        size,
        flags=cv2.INTER_AREA,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=white,
    )
