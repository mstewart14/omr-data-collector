"""The app icon, in the app and in the files for packaging it."""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest
from PySide6.QtGui import QImageReader
from PySide6.QtSvg import QSvgRenderer

from omr_data_collector.ui.app_icon import (
    DESKTOP_FILE_NAME,
    LARGE_SIZES,
    SMALL_ICON_FILE,
    SMALL_SIZES,
    _render,
    app_icon,
)

pytestmark = pytest.mark.usefixtures("qapp")

PACKAGING = Path(__file__).resolve().parents[1] / "packaging"


def test_the_icon_has_every_size_drawn_for_it() -> None:
    icon = app_icon()

    assert [size.width() for size in icon.availableSizes()] == [
        *SMALL_SIZES,
        *LARGE_SIZES,
    ]


def test_small_sizes_use_the_simpler_drawing() -> None:
    small = _render(QSvgRenderer(str(SMALL_ICON_FILE)), 16).toImage()

    assert app_icon().pixmap(16, 16).toImage() == small


@pytest.mark.parametrize(
    ("file_name", "sizes"),
    [
        (f"{DESKTOP_FILE_NAME}.ico", [16, 24, 32, 48, 64, 256]),
        (f"{DESKTOP_FILE_NAME}.icns", [16, 32, 64, 128, 256, 512]),
    ],
)
def test_the_packaged_icon_files_hold_every_size(
    file_name: str, sizes: list[int]
) -> None:
    reader = QImageReader(str(PACKAGING / "icons" / file_name))
    found = []
    for index in range(reader.imageCount()):
        reader.jumpToImage(index)
        found.append(reader.read().width())

    assert found == sizes


def test_the_linux_desktop_entry_names_the_icon() -> None:
    entry = configparser.ConfigParser(interpolation=None)
    entry.read(PACKAGING / "linux" / f"{DESKTOP_FILE_NAME}.desktop")

    desktop = entry["Desktop Entry"]
    assert desktop["Icon"] == DESKTOP_FILE_NAME
    assert desktop["Exec"] == "omr-data-collector"
