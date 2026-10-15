"""Toolbar icons for text formatting, drawn in the theme's own text color.

Drawn rather than taken from the system icon theme: Windows and macOS have no
freedesktop icon names, and Linux themes vary in which ones they have. Drawing in
the button's text color keeps the icons' contrast on light, dark and
high-contrast themes; they are redrawn when the theme changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap

if TYPE_CHECKING:
    from collections.abc import Callable

# Icons are drawn on a 16-unit grid and scaled to the size asked for.
GRID = 16.0


def _letter(
    letter: str, *, bold: bool, italic: bool
) -> Callable[[QPainter, QColor], None]:
    def draw(painter: QPainter, color: QColor) -> None:
        font = QFont()
        font.setPixelSize(round(GRID * 0.85))
        font.setBold(bold)
        font.setItalic(italic)
        painter.setFont(font)
        painter.setPen(QPen(color))
        painter.drawText(QRectF(0, 0, GRID, GRID), Qt.AlignmentFlag.AlignCenter, letter)

    return draw


def _list(numbered: bool) -> Callable[[QPainter, QColor], None]:  # noqa: FBT001
    def draw(painter: QPainter, color: QColor) -> None:
        line = QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        for row, y in enumerate((3.5, 8.0, 12.5)):
            if numbered:
                font = QFont()
                font.setPixelSize(6)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QPen(color))
                painter.drawText(
                    QRectF(0, y - 3.5, 5.5, 7),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(row + 1),
                )
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(QPointF(3.0, y), 1.6, 1.6)
            painter.setPen(line)
            painter.drawLine(QPointF(7.5, y), QPointF(14.5, y))

    return draw


DRAWINGS: dict[str, Callable[[QPainter, QColor], None]] = {
    "bold": _letter("B", bold=True, italic=False),
    "italic": _letter("I", bold=False, italic=True),
    "bulleted_list": _list(numbered=False),
    "numbered_list": _list(numbered=True),
}


def format_icon(
    name: str, color: QColor, size: int, device_pixel_ratio: float = 1.0
) -> QIcon:
    """Icon ``name`` (a key of ``DRAWINGS``) in ``color``, ``size`` pixels square."""
    pixels = max(round(size * device_pixel_ratio), 1)
    pixmap = QPixmap(pixels, pixels)
    pixmap.setDevicePixelRatio(device_pixel_ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.scale(pixels / GRID, pixels / GRID)
        DRAWINGS[name](painter, color)
    finally:
        painter.end()
    return QIcon(pixmap)
