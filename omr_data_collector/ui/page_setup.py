from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QPageLayout, QPageSize

from omr_data_collector.constants import PAGE_ORIENTATIONS, PAPER_SIZES

if TYPE_CHECKING:
    from omr_data_collector.models.Organization import Organization

PAGE_SIZE_IDS = {
    PAPER_SIZES.LETTER: QPageSize.PageSizeId.Letter,
    PAPER_SIZES.LEGAL: QPageSize.PageSizeId.Legal,
    PAPER_SIZES.A4: QPageSize.PageSizeId.A4,
}

PAGE_ORIENTATION_IDS = {
    PAGE_ORIENTATIONS.PORTRAIT: QPageLayout.Orientation.Portrait,
    PAGE_ORIENTATIONS.LANDSCAPE: QPageLayout.Orientation.Landscape,
}

# Most office printers can't print closer than about 6 mm to the edge.
PAGE_MARGIN_MM = 12.7


def page_layout(organization: Organization) -> QPageLayout:
    """The organization's page layout preference (wiki story 20001), as Qt's type."""
    return QPageLayout(
        QPageSize(PAGE_SIZE_IDS[organization.paper_size]),
        PAGE_ORIENTATION_IDS[organization.orientation],
        QMarginsF(PAGE_MARGIN_MM, PAGE_MARGIN_MM, PAGE_MARGIN_MM, PAGE_MARGIN_MM),
        QPageLayout.Unit.Millimeter,
    )
