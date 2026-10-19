"""The font the app's own windows use: the desktop's, at the size people choose.

Qt learns the desktop's font through a platform theme plugin. The Linux installer
leaves out the GTK one (its GTK clashes with the desktop's) and has no KDE one, so
there Qt falls back to a fixed font. ``desktop_font`` reads the setting itself:
KDE's ``kdeglobals``, or the XSETTINGS that XFCE, GNOME, MATE and Cinnamon publish
on X11. Printed forms don't use this font: each form names its own.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from omr_data_collector.i18n import preferences

TEXT_SIZE_SETTING = "textSize"
# The sizes Preferences > Text size offers, in points.
TEXT_SIZES = (9, 10, 11, 12, 13, 14, 15, 16, 18, 20, 22, 24, 28, 32)
XSETTINGS_FONT_NAME = "Gtk/FontName"

# Words a Pango font description ("Noto Sans Bold Italic 11") puts after the
# family, and the weight each sets.
PANGO_WEIGHTS = {
    "thin": QFont.Weight.Thin,
    "ultra-light": QFont.Weight.ExtraLight,
    "extra-light": QFont.Weight.ExtraLight,
    "light": QFont.Weight.Light,
    "semi-light": QFont.Weight.Light,
    "book": QFont.Weight.Normal,
    "regular": QFont.Weight.Normal,
    "normal": QFont.Weight.Normal,
    "medium": QFont.Weight.Medium,
    "semi-bold": QFont.Weight.DemiBold,
    "demi-bold": QFont.Weight.DemiBold,
    "bold": QFont.Weight.Bold,
    "ultra-bold": QFont.Weight.ExtraBold,
    "extra-bold": QFont.Weight.ExtraBold,
    "heavy": QFont.Weight.Black,
    "black": QFont.Weight.Black,
}
PANGO_SLANTS = {"italic", "oblique"}
PANGO_OTHER_STYLES = {
    "roman",
    "small-caps",
    "ultra-condensed",
    "extra-condensed",
    "condensed",
    "semi-condensed",
    "semi-expanded",
    "expanded",
    "extra-expanded",
    "ultra-expanded",
}

_desktop: QFont | None = None


def pango_font(description: str) -> QFont | None:
    """The font a Pango description such as "Noto Sans Bold 11" names, or None."""
    words = description.replace(",", " ").split()
    if not words:
        return None
    font = QFont()
    size = words[-1]
    try:
        if size.endswith("px"):
            font.setPixelSize(max(round(float(size[:-2])), 1))
        else:
            font.setPointSizeF(float(size))
        words.pop()
    except ValueError:
        pass
    while words and words[-1].lower() in (
        PANGO_WEIGHTS.keys() | PANGO_SLANTS | PANGO_OTHER_STYLES
    ):
        word = words.pop().lower()
        if word in PANGO_WEIGHTS:
            font.setWeight(PANGO_WEIGHTS[word])
        elif word in PANGO_SLANTS:
            font.setItalic(True)
    if not words:
        return None
    font.setFamily(" ".join(words))
    return font


def kde_font(kdeglobals: Path) -> QFont | None:
    """The [General] font in KDE's ``kdeglobals`` file, or None."""
    try:
        lines = kdeglobals.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    section = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
        elif section == "General" and stripped.startswith("font="):
            font = QFont()
            if font.fromString(stripped.removeprefix("font=")):
                return font
    return None


def xsettings_string(data: bytes, name: str) -> str | None:
    """A string setting from an X server's XSETTINGS block, or None.

    The block is the freedesktop.org XSETTINGS format: a byte order, a serial and
    a count, then each setting as its type, name and value, padded to 4 bytes.
    """

    def padded(length: int) -> int:
        return (length + 3) & ~3

    try:
        order = "<" if data[0] == 0 else ">"
        (count,) = struct.unpack_from(f"{order}I", data, 8)
        offset = 12
        for _ in range(count):
            kind, name_length = struct.unpack_from(f"{order}BxH", data, offset)
            offset += 4
            setting = data[offset : offset + name_length].decode()
            offset += padded(name_length) + 4  # the name, then its last-change serial
            if kind == 0:  # an integer
                offset += 4
            elif kind == 1:  # a string
                (length,) = struct.unpack_from(f"{order}I", data, offset)
                value = data[offset + 4 : offset + 4 + length].decode()
                if setting == name:
                    return value
                offset += 4 + padded(length)
            elif kind == 2:  # a colour, four 16-bit channels
                offset += 8
            else:
                return None
    except (IndexError, struct.error, UnicodeDecodeError):
        return None
    return None


def _x11_library() -> ctypes.CDLL | None:
    """Xlib, with the signatures of the calls ``_x11_xsettings`` makes; or None."""
    # find_library asks ldconfig, which not every system has on the path.
    library = ctypes.util.find_library("X11") or "libX11.so.6"
    try:
        x11 = ctypes.CDLL(library)
    except OSError:
        return None
    pointer = ctypes.c_void_p
    x11.XOpenDisplay.restype = pointer
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultScreen.argtypes = [pointer]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [pointer, ctypes.c_char_p, ctypes.c_int]
    x11.XGetSelectionOwner.restype = ctypes.c_ulong
    x11.XGetSelectionOwner.argtypes = [pointer, ctypes.c_ulong]
    x11.XGetWindowProperty.argtypes = [
        pointer,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_long,
        ctypes.c_long,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
    ]
    x11.XFree.argtypes = [pointer]
    x11.XCloseDisplay.argtypes = [pointer]
    return x11


def _x11_xsettings() -> bytes | None:
    """The XSETTINGS block of the X server in DISPLAY, or None."""
    x11 = _x11_library() if os.environ.get("DISPLAY") else None
    display = x11.XOpenDisplay(None) if x11 is not None else None
    if x11 is None or not display:
        return None
    try:
        screen = x11.XDefaultScreen(display)
        selection = x11.XInternAtom(display, f"_XSETTINGS_S{screen}".encode(), 0)
        owner = x11.XGetSelectionOwner(display, selection)
        settings = x11.XInternAtom(display, b"_XSETTINGS_SETTINGS", 0)
        kind = ctypes.c_ulong()
        bits = ctypes.c_int()
        items = ctypes.c_ulong()
        remaining = ctypes.c_ulong()
        data = ctypes.POINTER(ctypes.c_ubyte)()
        # No owner means no settings daemon is running.
        status = (
            x11.XGetWindowProperty(
                display,
                owner,
                settings,
                0,
                0x7FFFFFFF,
                0,
                settings,
                ctypes.byref(kind),
                ctypes.byref(bits),
                ctypes.byref(items),
                ctypes.byref(remaining),
                ctypes.byref(data),
            )
            if owner
            else 1
        )
        if status != 0 or not data:
            return None
        try:
            # XSETTINGS is a byte string: anything else isn't it.
            return ctypes.string_at(data, items.value) if bits.value == 8 else None
        finally:
            x11.XFree(data)
    finally:
        x11.XCloseDisplay(display)


def desktop_font() -> QFont | None:
    """The desktop's own font for windows, where Qt can't know it; else None."""
    if not sys.platform.startswith("linux"):
        return None
    if "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":"):
        config = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.GenericConfigLocation
        )
        font = kde_font(Path(config) / "kdeglobals")
        if font is not None:
            return font
    data = _x11_xsettings()
    description = xsettings_string(data, XSETTINGS_FONT_NAME) if data else None
    return pango_font(description) if description else None


def remember_desktop_font() -> QFont:
    """Note the desktop's font, before any size chosen in the app replaces it."""
    global _desktop  # noqa: PLW0603 (read once, when the app starts)
    _desktop = desktop_font() or QApplication.font()
    return _desktop


def desktop_text_font() -> QFont:
    """The desktop's font for windows (Qt's own if it can't be read)."""
    return QFont(_desktop if _desktop is not None else remember_desktop_font())


def saved_text_size() -> float:
    """The size chosen in Preferences > Text size, in points; 0 for the desktop's."""
    value = preferences().value(TEXT_SIZE_SETTING, 0)
    try:
        size = float(value)  # pyright: ignore[reportArgumentType] (an ini value)
    except (TypeError, ValueError):
        return 0
    return max(0, size)


def save_text_size(size: float) -> None:
    """Remember the text size (0 for the desktop's) for this and later starts."""
    settings = preferences()
    settings.setValue(TEXT_SIZE_SETTING, size)
    settings.sync()


def apply_text_size(size: float) -> None:
    """Use the desktop's font in every window, at ``size`` points (0: its own)."""
    font = desktop_text_font()
    if size > 0:
        font.setPointSizeF(size)
    QApplication.setFont(font)
