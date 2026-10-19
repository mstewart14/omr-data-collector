"""The text-formatting icons, drawn the same on ordinary and high-density screens."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage

from omr_data_collector.ui.format_icons import DRAWINGS, format_icon

SIZE = 32


def inked_area(name: str, device_pixel_ratio: float) -> QRect:
    """Where the icon is drawn, in its own (logical) pixels."""
    icon = format_icon(name, QColor("black"), SIZE, device_pixel_ratio)
    image = icon.pixmap(icon.availableSizes()[0]).toImage()
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    inked = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 0
    ]
    xs = [x for x, _ in inked]
    ys = [y for _, y in inked]
    ratio = device_pixel_ratio
    return QRect(
        round(min(xs) / ratio),
        round(min(ys) / ratio),
        round((max(xs) - min(xs)) / ratio),
        round((max(ys) - min(ys)) / ratio),
    )


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize("name", list(DRAWINGS))
def test_a_retina_icon_is_the_same_drawing_in_finer_pixels(name: str) -> None:
    # On a Retina Mac (ratio 2) the drawing was doubled and cut off at the edge.
    ordinary = inked_area(name, 1.0)
    retina = inked_area(name, 2.0)

    for side in ("left", "top", "width", "height"):
        assert abs(getattr(retina, side)() - getattr(ordinary, side)()) <= 1, side
    assert retina.right() < SIZE - 1
    assert retina.bottom() < SIZE - 1
