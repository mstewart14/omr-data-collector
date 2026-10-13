"""A page drawn as a photo of it filled in would show it.

For the installer self-check (``self_check``) and the tests that scan sheets:
the page on a grey background at a chosen resolution, with bubbles filled in
as a pen would.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from omr_data_collector.layout.page_setup import PAGE_MARGIN_MM
from omr_data_collector.rendering.page_painter import paint_page

if TYPE_CHECKING:
    from omr_data_collector.layout.form_layout import FormLayout, PageLayout
    from omr_data_collector.models.Form import Form
    from omr_data_collector.models.Organization import Organization

# The table showing around the sheet.
BACKGROUND = QColor("#707070")
# A pen mark filling a 3 mm bubble, and a little over its edge.
FILL_RADIUS_MM = 1.6


def begin_page_photo(  # noqa: PLR0913 (what to draw, and how big)
    form: Form,
    organization: Organization,
    layout: FormLayout,
    page: PageLayout,
    pixels_per_mm: float,
    border_mm: float,
) -> tuple[QImage, QPainter]:
    """Draw ``page`` on grey, ``border_mm`` of it showing around the paper.

    Returns the image and a painter still drawing on it, in millimetres from the
    printable area's top-left (where the layout places blocks), with a black
    brush for ``fill_bubble``. End the painter before using the image, and
    always end it: Qt crashes if the image goes first.
    """
    image = QImage(
        round((layout.paper_width_mm + 2 * border_mm) * pixels_per_mm),
        round((layout.paper_height_mm + 2 * border_mm) * pixels_per_mm),
        QImage.Format.Format_RGB32,
    )
    image.fill(BACKGROUND)
    painter = QPainter(image)
    try:
        painter.scale(pixels_per_mm, pixels_per_mm)
        painter.translate(border_mm, border_mm)
        painter.fillRect(
            0,
            0,
            round(layout.paper_width_mm),
            round(layout.paper_height_mm),
            QColor("white"),
        )
        painter.translate(PAGE_MARGIN_MM, PAGE_MARGIN_MM)
        paint_page(painter, form, organization, layout, page)
    except BaseException:
        painter.end()
        raise
    # Marks are the brush alone: an outline would darken every mark, however
    # small or pale.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("black"))
    return image, painter


def fill_bubble(
    painter: QPainter, x_mm: float, y_mm: float, radius_mm: float = FILL_RADIUS_MM
) -> None:
    """Fill in the bubble centred at (``x_mm``, ``y_mm``) on the page.

    A ``radius_mm`` under the bubble's own 1.5 mm fills only its middle, as a
    mark begun but not finished does.
    """
    painter.drawEllipse(QPointF(x_mm, y_mm), radius_mm, radius_mm)
