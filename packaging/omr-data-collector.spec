# PyInstaller recipe for the app, on every platform (see packaging/README.md).
#
#   uv run pyinstaller --noconfirm packaging/omr-data-collector.spec
#
# Writes dist/omr-data-collector/ (a folder, not one file: it starts faster, and
# keeps Qt as separate libraries, as the LGPL asks), plus on macOS
# dist/OMR Data Collector.app. The installer scripts beside this file wrap those.
# ruff: noqa (PyInstaller runs this with Analysis, EXE and the rest predefined)

import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH).parent
PACKAGE = ROOT / "omr_data_collector"
ICONS = ROOT / "packaging" / "icons"
NAME = "omr-data-collector"
DISPLAY_NAME = "OMR Data Collector"
GTK_ONLY = ("libqgtk3", "libgtk-3", "libgdk-3", "libgdk_pixbuf", "libatk")
# Taken from the desktop instead. libxkbcommon-x11 isn't bundled, so Qt loads the
# system's, and it fills in libxkbcommon's internal structures directly: with the
# build machine's older libxkbcommon beside a newer system one, the first key
# pressed under X11 crashes the app.
FROM_SYSTEM = ("libxkbcommon",)
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]

a = Analysis(
    [str(PACKAGE / "__main__.py")],
    # OMRChecker's package is named src and lives in its repository root, which
    # omr_data_collector.engine puts on the path at run time.
    pathex=[str(ROOT), str(ROOT / "vendor" / "omrchecker")],
    datas=[
        (str(PACKAGE / "translations" / "*.qm"), "omr_data_collector/translations"),
        (str(PACKAGE / "resources" / "*.svg"), "omr_data_collector/resources"),
        # The package's own metadata, which About reads the version from.
        *copy_metadata(NAME),
    ],
    excludes=[
        # OMRChecker imports these only for barcode and OCR fields, which our
        # templates never have (see pyproject.toml).
        "pyzbar",
        "easyocr",
        "tkinter",
        "IPython",
        "pytest",
    ],
    noarchive=False,
)
if sys.platform.startswith("linux"):
    # Qt's GTK theme plugin would bring the build machine's GTK along, which
    # clashes with the GTK of the desktop it runs on; Qt draws its own instead.
    a.binaries = [
        entry
        for entry in a.binaries
        if not any(part in Path(entry[0]).name for part in GTK_ONLY + FROM_SYSTEM)
    ]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,
    icon=str(ICONS / (f"{NAME}.icns" if sys.platform == "darwin" else f"{NAME}.ico")),
    # Stripping and UPX can break Qt's and OpenCV's libraries; size isn't worth it.
    strip=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, strip=False, upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{DISPLAY_NAME}.app",
        icon=str(ICONS / f"{NAME}.icns"),
        bundle_identifier="ca.stewartclan.omr-data-collector",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": DISPLAY_NAME,
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
