# ruff: noqa: INP001 (a standalone tool, not part of a package)
"""Build the app icon's files for packaging from its SVG drawings.

usage: uv run python scripts/build_icons.py

Writes into packaging/:
- icons/png/<size>.png at the usual sizes (Linux hicolor themes, installers);
- icons/omr-data-collector.ico for Windows, several sizes in one file;
- icons/omr-data-collector.icns for macOS, likewise.

The small sizes come from app-icon-small.svg, drawn with fewer, bigger bubbles;
the rest from app-icon.svg. Run it after changing either drawing.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "omr_data_collector" / "resources"
OUT = ROOT / "packaging" / "icons"
NAME = "omr-data-collector"
PNG_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)
SMALL_UP_TO = 24
ICO_SIZES = (16, 24, 32, 48, 64, 256)
# macOS icon types holding PNG data, by pixel size.
ICNS_TYPES = {
    16: b"icp4",
    32: b"icp5",
    64: b"icp6",
    128: b"ic07",
    256: b"ic08",
    512: b"ic09",
}


def png(size: int) -> bytes:
    """The icon drawn at ``size`` pixels square, as PNG data."""
    drawing = "app-icon-small.svg" if size <= SMALL_UP_TO else "app-icon.svg"
    renderer = QSvgRenderer(str(RESOURCES / drawing))
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data.data())


def ico(images: dict[int, bytes]) -> bytes:
    """A Windows icon file holding each image as PNG (Windows Vista and later)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, payload = b"", b""
    for size, data in images.items():
        # 0 stands for 256 in the one-byte width and height.
        side = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset + len(payload)
        )
        payload += data
    return header + entries + payload


def icns(images: dict[int, bytes]) -> bytes:
    """A macOS icon file holding each image as PNG."""
    body = b"".join(
        ICNS_TYPES[size] + struct.pack(">I", len(data) + 8) + data
        for size, data in images.items()
    )
    return b"icns" + struct.pack(">I", len(body) + 8) + body


def main() -> None:
    QApplication(sys.argv[:1])
    images = {size: png(size) for size in PNG_SIZES}
    (OUT / "png").mkdir(parents=True, exist_ok=True)
    for size, data in images.items():
        (OUT / "png" / f"{size}.png").write_bytes(data)
    (OUT / f"{NAME}.ico").write_bytes(ico({s: images[s] for s in ICO_SIZES}))
    (OUT / f"{NAME}.icns").write_bytes(icns({s: images[s] for s in ICNS_TYPES}))


if __name__ == "__main__":
    main()
