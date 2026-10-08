"""Measuring and drawing text in printed sizes (points and millimetres).

Everything on paper is laid out in millimetres. Text is measured against a
reference that is exactly 72 dots per inch, so one point is one unit there, and
the result is the same on any screen or printer; drawing then scales from that
reference to the page.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF
from PySide6.QtGui import QFont, QFontMetricsF, QImage, QTextDocument

if TYPE_CHECKING:
    from PySide6.QtGui import QPainter

MM_PER_POINT = 25.4 / 72
# GitHub-flavoured Markdown without raw HTML: anything HTML-like is kept as literal
# text, so stored text holds only the formatting the editor offers.
MARKDOWN_FEATURES = (
    QTextDocument.MarkdownFeature.MarkdownDialectGitHub
    | QTextDocument.MarkdownFeature.MarkdownNoHTML
)
INCHES_PER_METRE = 1 / 0.0254
# Text is measured with fonts this many pixels tall, then scaled: big enough that
# rounding is negligible.
MEASURING_PIXEL_SIZE = 100
# Drawing works in tenths of a point, so font sizes like 7.5 pt stay exact even
# though Qt font pixel sizes are whole numbers.
DRAW_UNITS_PER_POINT = 10

_reference_device: QImage | None = None


def _reference() -> QImage:
    """A 72-dpi surface for laying out documents, so 1 point is 1 unit."""
    global _reference_device  # noqa: PLW0603 (one shared, lazily made device)
    if _reference_device is None:
        _reference_device = QImage(1, 1, QImage.Format.Format_RGB32)
        dots_per_metre = round(72 * INCHES_PER_METRE)
        _reference_device.setDotsPerMeterX(dots_per_metre)
        _reference_device.setDotsPerMeterY(dots_per_metre)
    return _reference_device


def measuring_font(*, bold: bool = False, italic: bool = False) -> QFont:
    font = QFont()
    font.setPixelSize(MEASURING_PIXEL_SIZE)
    font.setBold(bold)
    font.setItalic(italic)
    return font


def text_width_mm(
    text: str, point_size: float, *, bold: bool = False, italic: bool = False
) -> float:
    """The printed width of one line of ``text`` at ``point_size``."""
    advance = QFontMetricsF(measuring_font(bold=bold, italic=italic)).horizontalAdvance(
        text
    )
    return advance / MEASURING_PIXEL_SIZE * point_size * MM_PER_POINT


def line_height_mm(point_size: float) -> float:
    spacing = QFontMetricsF(measuring_font()).lineSpacing()
    return spacing / MEASURING_PIXEL_SIZE * point_size * MM_PER_POINT


def markdown_document(
    markdown: str, width_mm: float, point_size: float
) -> QTextDocument:
    """Markdown laid out ``width_mm`` wide in ``point_size`` text, ready to measure."""
    document = QTextDocument()
    document.documentLayout().setPaintDevice(_reference())
    font = QFont()
    font.setPointSizeF(point_size)
    document.setDefaultFont(font)
    document.setDocumentMargin(0)
    document.setMarkdown(markdown, MARKDOWN_FEATURES)
    document.setTextWidth(width_mm / MM_PER_POINT)
    return document


def document_height_mm(document: QTextDocument) -> float:
    return document.size().height() * MM_PER_POINT


def draw_document(
    painter: QPainter, document: QTextDocument, x_mm: float, y_mm: float
) -> None:
    """Draw a document from ``markdown_document`` with a painter working in mm."""
    painter.save()
    painter.translate(x_mm, y_mm)
    painter.scale(MM_PER_POINT, MM_PER_POINT)
    document.drawContents(painter)
    painter.restore()


def draw_text(  # noqa: PLR0913 (where, what and how it looks)
    painter: QPainter,
    rect_mm: QRectF,
    flags: int,
    text: str,
    point_size: float,
    *,
    bold: bool = False,
    italic: bool = False,
) -> None:
    """Draw ``text`` in ``rect_mm`` with a painter working in millimetres."""
    scale = MM_PER_POINT / DRAW_UNITS_PER_POINT
    painter.save()
    painter.scale(scale, scale)
    font = QFont()
    font.setPixelSize(max(round(point_size * DRAW_UNITS_PER_POINT), 1))
    font.setBold(bold)
    font.setItalic(italic)
    painter.setFont(font)
    painter.drawText(
        QRectF(
            rect_mm.x() / scale,
            rect_mm.y() / scale,
            rect_mm.width() / scale,
            rect_mm.height() / scale,
        ),
        flags,
        text,
    )
    painter.restore()


def plain_document(
    text: str, width_mm: float, point_size: float, *, italic: bool = False
) -> QTextDocument:
    """Plain text (no Markdown) laid out ``width_mm`` wide, ready to measure."""
    document = QTextDocument()
    document.documentLayout().setPaintDevice(_reference())
    font = QFont()
    font.setPointSizeF(point_size)
    font.setItalic(italic)
    document.setDefaultFont(font)
    document.setDocumentMargin(0)
    document.setPlainText(text)
    document.setTextWidth(width_mm / MM_PER_POINT)
    return document
