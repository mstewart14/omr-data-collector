"""Prints a form, or saves it as a PDF, from the same layout the editor shows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QPainter, QPdfWriter
from PySide6.QtPrintSupport import QPrinter

from omr_data_collector.i18n import tr
from omr_data_collector.layout.form_layout import layout_form
from omr_data_collector.layout.page_setup import PAGE_MARGIN_MM, page_layout_for
from omr_data_collector.rendering.page_painter import paint_page

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtGui import QPagedPaintDevice

    from omr_data_collector.layout.form_layout import FormLayout
    from omr_data_collector.models.Form import Form
    from omr_data_collector.models.Organization import Organization

# Fine enough that bubbles and QR modules have crisp edges; Qt PDFs are vector
# anyway, so this mainly sets how finely positions are rounded.
PDF_RESOLUTION_DPI = 600
MM_PER_INCH = 25.4


def render_form(
    device: QPagedPaintDevice,
    form: Form,
    organization: Organization,
    paper_size: str,
    layout: FormLayout | None = None,
) -> int:
    """Draw every page of ``form`` on ``device`` (a printer or PDF writer).

    ``layout`` is a printed version's frozen one (``frozen_layout``); without
    it the form is laid out now.

    The device draws the whole sheet (no margins of its own), and the painter is
    moved to the top-left of the printable area, as the layout expects: the
    corner markers are drawn out in the margins, which a device's own margins
    would clip.

    Returns:
        The number of pages drawn.
    """
    full_sheet = page_layout_for(paper_size, form.orientation)
    full_sheet.setMargins(QMarginsF(0, 0, 0, 0))
    if isinstance(device, QPrinter):
        # Coordinates from the paper's corner, not the printer's printable area.
        device.setFullPage(True)
    device.setPageLayout(full_sheet)
    if layout is None:
        layout = layout_form(form, paper_size)
    painter = QPainter()
    if not painter.begin(device):
        msg = tr("The printer or file could not be opened for drawing.")
        raise OSError(msg)
    try:
        pixels_per_mm = device.logicalDpiX() / MM_PER_INCH
        for page in layout.pages:
            if page.number > 1:
                device.newPage()
            painter.save()
            painter.scale(pixels_per_mm, pixels_per_mm)
            painter.translate(PAGE_MARGIN_MM, PAGE_MARGIN_MM)
            paint_page(painter, form, organization, layout, page)
            painter.restore()
    finally:
        painter.end()
    return len(layout.pages)


def save_pdf(
    path: Path,
    form: Form,
    organization: Organization,
    paper_size: str,
    layout: FormLayout | None = None,
) -> int:
    """Save ``form`` as a PDF at ``path``; returns the number of pages."""
    writer = QPdfWriter(str(path))
    writer.setResolution(PDF_RESOLUTION_DPI)
    writer.setTitle(
        tr("{name} (version {version})").format(name=form.name, version=form.version)
    )
    writer.setCreator("OMR Data Collector")
    pages = render_form(writer, form, organization, paper_size, layout)
    # The file is finished when the writer is deleted.
    del writer
    return pages
