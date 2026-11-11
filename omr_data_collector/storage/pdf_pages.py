"""PDF scans (from a scanner or a phone scanning app) as one image per page.

A scanning app such as Adobe Scan saves its pages as a PDF, already cropped to
the paper and turned the right way. Each page is drawn as an image so it can be
added and read like a photo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPainter

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtPdf import QPdfDocument

# Sharp enough for the bubbles and the QR code (scanning apps keep about this),
# without making huge files of large pages.
PAGE_DPI = 300
MAX_PAGE_PIXELS = 6000
POINTS_PER_INCH = 72


class PdfError(Exception):
    """The PDF couldn't be opened (damaged, password-protected or not a PDF)."""


@dataclass(frozen=True)
class PdfPage:
    number: int  # from 1
    image: Path


def is_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


def pdf_page_images(pdf: Path, out_dir: Path) -> list[PdfPage]:
    """Draw every page of ``pdf`` as a PNG in ``out_dir``, on white paper.

    Raises:
        PdfError: The file couldn't be opened as a PDF, or has no pages.
    """
    # Imported here: only adding a PDF needs Qt's PDF module, not starting up.
    from PySide6.QtPdf import QPdfDocument  # noqa: PLC0415

    document = QPdfDocument()
    if document.load(str(pdf)) != QPdfDocument.Error.None_ or not document.pageCount():
        document.close()
        raise PdfError(pdf.name)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    try:
        for index in range(document.pageCount()):
            image = _on_white(document.render(index, _page_pixels(document, index)))
            path = out_dir / f"{pdf.stem}-page-{index + 1}.png"
            if image.isNull() or not image.save(str(path)):
                raise PdfError(pdf.name)
            pages.append(PdfPage(number=index + 1, image=path))
    finally:
        document.close()
    return pages


def _page_pixels(document: QPdfDocument, index: int) -> QSize:
    """The page's size in pixels at PAGE_DPI, its longer side capped."""
    points = document.pagePointSize(index)
    scale = PAGE_DPI / POINTS_PER_INCH
    longest = max(points.width(), points.height()) * scale
    if longest > MAX_PAGE_PIXELS:
        scale *= MAX_PAGE_PIXELS / longest
    return QSize(
        max(1, round(points.width() * scale)), max(1, round(points.height() * scale))
    )


def _on_white(page: QImage) -> QImage:
    """The page over white: what PDF leaves transparent would read as black."""
    if page.isNull():
        return page
    paper = QImage(page.size(), QImage.Format.Format_RGB32)
    paper.fill(Qt.GlobalColor.white)
    painter = QPainter(paper)
    painter.drawImage(0, 0, page)
    painter.end()
    return paper
