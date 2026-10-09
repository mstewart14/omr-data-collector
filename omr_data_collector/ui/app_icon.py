"""The app's icon: a form whose lines are rows of answer bubbles."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

RESOURCES = Path(__file__).resolve().parents[1] / "resources"
ICON_FILE = RESOURCES / "app-icon.svg"
# Drawn with fewer, bigger bubbles, for the sizes where the full icon blurs.
SMALL_ICON_FILE = RESOURCES / "app-icon-small.svg"
SMALL_SIZES = (16, 20, 22, 24)
LARGE_SIZES = (32, 40, 48, 64, 96, 128, 256, 512)
# Matches packaging/linux/omr-data-collector.desktop, which is how Linux desktops
# (Wayland in particular) find the icon for the task bar.
DESKTOP_FILE_NAME = "omr-data-collector"


def app_icon() -> QIcon:
    """The icon at each size, each drawn from the version made for it.

    Rendered here rather than given to Qt as SVG files: Qt's SVG icons keep
    one drawing for every size, which would lose the small version.
    """
    icon = QIcon()
    for drawing, sizes in ((SMALL_ICON_FILE, SMALL_SIZES), (ICON_FILE, LARGE_SIZES)):
        renderer = QSvgRenderer(str(drawing))
        for size in sizes:
            icon.addPixmap(_render(renderer, size))
    return icon


def _render(renderer: QSvgRenderer, size: int) -> QPixmap:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QPixmap.fromImage(image)
