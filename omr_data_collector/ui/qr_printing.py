from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QImage, QPainter

from omr_data_collector.identity.qr_code import (
    build_organization_payload,
    make_qr_code,
    qr_code_png,
)

if TYPE_CHECKING:
    from PySide6.QtGui import QPagedPaintDevice

    from omr_data_collector.models.Organization import Organization

# Printed width of the code itself, quiet zone included. 50 mm stays readable from a
# phone held well back from the page.
PRINTED_QR_WIDTH_MM = 50
CAPTION_GAP_MM = 6
CAPTION_POINT_SIZE = 14


def paint_organization_qr_page(
    device: QPagedPaintDevice, organization: Organization
) -> None:
    """Paint one page: the organization's QR code, centred, with its name below.

    ``device`` is a printer from the print dialog, or a ``QPdfWriter`` in tests.
    """
    qr_code = make_qr_code(build_organization_payload(organization))
    # One pixel per module; the painter scales it up without smoothing, so module
    # edges stay sharp at any printer resolution.
    image = QImage.fromData(qr_code_png(qr_code, scale=1))

    painter = QPainter(device)
    try:
        dots_per_inch = device.logicalDpiX()
        page = device.pageLayout().paintRectPixels(dots_per_inch)
        dots_per_mm = dots_per_inch / 25.4
        side = PRINTED_QR_WIDTH_MM * dots_per_mm
        top = page.top() + page.height() / 4
        target = QRectF(page.center().x() - side / 2, top, side, side)

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, on=False)
        painter.drawImage(target, image)

        font = QFont()
        font.setPointSize(CAPTION_POINT_SIZE)
        painter.setFont(font)
        caption = QRectF(
            page.left(),
            target.bottom() + CAPTION_GAP_MM * dots_per_mm,
            page.width(),
            page.height() / 4,
        )
        painter.drawText(
            caption,
            Qt.AlignmentFlag.AlignHCenter
            | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap,
            organization.name,
        )
    finally:
        painter.end()
