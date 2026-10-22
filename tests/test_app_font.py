from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel

from omr_data_collector.ui import app_font
from omr_data_collector.ui.app_font import (
    apply_text_size,
    desktop_font,
    kde_font,
    pango_font,
    save_text_size,
    saved_text_size,
    xsettings_string,
)
from omr_data_collector.ui.MainWindow import MainWindow
from omr_data_collector.ui.TextSizeDialog import TextSizeDialog

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot


@pytest.fixture(autouse=True)
def desktop(monkeypatch: pytest.MonkeyPatch) -> QFont:
    """A known desktop font (conftest puts the app's own back afterwards)."""
    font = QFont("Noto Sans")
    font.setPointSizeF(15)
    monkeypatch.setattr(app_font, "_desktop", font)
    return font


def xsettings(*settings: tuple[int, str, object], big_endian: bool = False) -> bytes:
    """An XSETTINGS block holding ``settings`` as (type, name, value)."""
    order = ">" if big_endian else "<"

    def pad(data: bytes) -> bytes:
        return data + b"\0" * (-len(data) % 4)

    block = struct.pack(f"{order}B3xII", int(big_endian), 1, len(settings))
    for kind, name, value in settings:
        block += struct.pack(f"{order}BxH", kind, len(name)) + pad(name.encode())
        block += struct.pack(f"{order}I", 0)
        if kind == 0:
            block += struct.pack(f"{order}i", value)
        elif kind == 1:
            text = str(value).encode()
            block += struct.pack(f"{order}I", len(text)) + pad(text)
        else:
            block += struct.pack(f"{order}4H", *value)  # pyright: ignore[reportGeneralTypeIssues]
    return block


# --- Reading the desktop's font ------------------------------------------------


@pytest.mark.parametrize(
    ("description", "family", "size", "weight", "italic"),
    [
        ("Noto Sans 15", "Noto Sans", 15, QFont.Weight.Normal, False),
        ("Cantarell 10.5", "Cantarell", 10.5, QFont.Weight.Normal, False),
        ("DejaVu Sans Bold Italic 9", "DejaVu Sans", 9, QFont.Weight.Bold, True),
        ("Ubuntu Semi-Bold 11", "Ubuntu", 11, QFont.Weight.DemiBold, False),
        ("Fira Sans Condensed Light 12", "Fira Sans", 12, QFont.Weight.Light, False),
    ],
)
def test_desktop_font_descriptions_are_read(
    description: str,
    family: str,
    size: float,
    weight: QFont.Weight,
    italic: bool,  # noqa: FBT001 (a parameter of the test)
) -> None:
    font = pango_font(description)

    assert font is not None
    assert (font.family(), font.pointSizeF(), font.weight(), font.italic()) == (
        family,
        size,
        weight,
        italic,
    )


def test_a_description_in_pixels_sets_a_pixel_size() -> None:
    font = pango_font("Sans 20px")

    assert font is not None
    assert font.pixelSize() == 20


@pytest.mark.parametrize("description", ["", "   ", "Bold 10"])
def test_a_description_without_a_family_is_no_font(description: str) -> None:
    assert pango_font(description) is None


def test_kde_font_comes_from_the_general_section(tmp_path: Path) -> None:
    kdeglobals = tmp_path / "kdeglobals"
    kdeglobals.write_text(
        "[WM]\nfont=Wrong,9,-1,5,50,0,0,0,0,0\n"
        "[General]\nColorScheme=BreezeDark\nfont=Noto Sans,13,-1,5,50,0,0,0,0,0\n",
        encoding="utf-8",
    )

    font = kde_font(kdeglobals)

    assert font is not None
    assert (font.family(), font.pointSizeF()) == ("Noto Sans", 13)


def test_no_kde_settings_is_no_font(tmp_path: Path) -> None:
    assert kde_font(tmp_path / "missing") is None


@pytest.mark.parametrize("big_endian", [False, True], ids=["lsb", "msb"])
def test_the_font_setting_is_found_among_others(big_endian: bool) -> None:  # noqa: FBT001
    data = xsettings(
        (0, "Net/DoubleClickTime", 400),
        (2, "Gtk/Color", (1, 2, 3, 4)),
        (1, "Net/ThemeName", "Greybird"),
        (1, "Gtk/FontName", "Noto Sans 15"),
        big_endian=big_endian,
    )

    assert xsettings_string(data, "Gtk/FontName") == "Noto Sans 15"
    assert xsettings_string(data, "Gtk/Missing") is None


def test_a_cut_off_settings_block_is_ignored() -> None:
    data = xsettings((1, "Gtk/FontName", "Noto Sans 15"))

    assert xsettings_string(data[:20], "Gtk/FontName") is None


def test_linux_desktops_font_comes_from_xsettings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_font.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "XFCE")
    monkeypatch.setattr(
        app_font, "_x11_xsettings", lambda: xsettings((1, "Gtk/FontName", "Lato 14"))
    )

    font = desktop_font()

    assert font is not None
    assert (font.family(), font.pointSizeF()) == ("Lato", 14)


def test_kde_uses_its_own_settings(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, tmp_path: Path
) -> None:
    (tmp_path / "kdeglobals").write_text(
        "[General]\nfont=Hack,12,-1,5,50,0,0,0,0,0\n", encoding="utf-8"
    )
    monkeypatch.setattr(app_font.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    mocker.patch.object(
        app_font.QStandardPaths, "writableLocation", return_value=str(tmp_path)
    )
    xsettings_read = mocker.patch.object(app_font, "_x11_xsettings")

    font = desktop_font()

    assert font is not None
    assert font.family() == "Hack"
    xsettings_read.assert_not_called()


def test_other_systems_leave_the_font_to_qt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_font.sys, "platform", "win32")

    assert desktop_font() is None


# --- The text size preference --------------------------------------------------


def test_the_desktop_size_is_the_default() -> None:
    assert saved_text_size() == 0


def test_a_chosen_size_is_remembered() -> None:
    save_text_size(18)

    assert saved_text_size() == 18


def test_a_damaged_setting_falls_back_to_the_desktop() -> None:
    app_font.preferences().setValue(app_font.TEXT_SIZE_SETTING, "huge")

    assert saved_text_size() == 0


@pytest.mark.parametrize(
    ("stored", "read"), [("2", 9), ("500", 32), ("inf", 32), ("nan", 0), ("-4", 0)]
)
def test_an_edited_setting_is_held_to_the_sizes_offered(
    stored: str, read: float
) -> None:
    app_font.preferences().setValue(app_font.TEXT_SIZE_SETTING, stored)

    assert saved_text_size() == read


def test_the_app_uses_the_desktop_font(qapp: QApplication) -> None:
    apply_text_size(0)

    assert (qapp.font().family(), qapp.font().pointSizeF()) == ("Noto Sans", 15)


def test_a_chosen_size_keeps_the_desktop_typeface(qapp: QApplication) -> None:
    apply_text_size(20)

    assert (qapp.font().family(), qapp.font().pointSizeF()) == ("Noto Sans", 20)


# --- Preferences > Text size ---------------------------------------------------


def test_the_dialog_offers_the_desktop_size_first(qtbot: QtBot) -> None:
    dialog = TextSizeDialog(None, 0)
    qtbot.addWidget(dialog)

    assert dialog.size_combo.itemText(0) == "Same as the desktop (15 pt)"
    assert dialog.chosen_size() == 0

    dialog.size_combo.setCurrentIndex(dialog.size_combo.findData(24.0))

    assert dialog.chosen_size() == 24


def test_the_dialog_starts_on_the_current_size_even_if_unlisted(
    qtbot: QtBot,
) -> None:
    dialog = TextSizeDialog(None, 17)
    qtbot.addWidget(dialog)

    assert dialog.chosen_size() == 17
    assert dialog.size_combo.currentText() == "17 pt"


def test_the_dialog_labels_its_list_for_screen_readers(qtbot: QtBot) -> None:
    dialog = TextSizeDialog(None, 0)
    qtbot.addWidget(dialog)

    (label,) = [
        label
        for label in dialog.findChildren(QLabel)
        if label.buddy() is dialog.size_combo
    ]

    assert label.text() == "Text &size"


def make_window(qtbot: QtBot, connection: sqlite3.Connection) -> MainWindow:
    window = MainWindow(connection)
    qtbot.addWidget(window)
    return window


def test_choosing_a_size_applies_it_at_once_and_says_so(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    qapp: QApplication,
) -> None:
    window = make_window(qtbot, connection)
    mocker.patch("omr_data_collector.ui.MainWindow.choose_text_size", return_value=18)
    announce = mocker.patch("omr_data_collector.ui.MainWindow.announce")

    window.change_text_size()

    assert saved_text_size() == 18
    assert qapp.font().pointSizeF() == 18
    announce.assert_called_once_with(window, "The app's text is now 18 pt.")


def test_going_back_to_the_desktop_size(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    qapp: QApplication,
) -> None:
    save_text_size(18)
    apply_text_size(18)
    window = make_window(qtbot, connection)
    mocker.patch("omr_data_collector.ui.MainWindow.choose_text_size", return_value=0)

    window.change_text_size()

    assert saved_text_size() == 0
    assert qapp.font().pointSizeF() == 15
    assert "follows the desktop" in window.statusBar().currentMessage()


@pytest.mark.parametrize("answer", [None, 0], ids=["cancelled", "unchanged"])
def test_cancelling_or_keeping_the_size_changes_nothing(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    answer: float | None,
) -> None:
    window = make_window(qtbot, connection)
    mocker.patch(
        "omr_data_collector.ui.MainWindow.choose_text_size", return_value=answer
    )
    save = mocker.patch("omr_data_collector.ui.MainWindow.save_text_size")

    window.change_text_size()

    save.assert_not_called()
    assert window.statusBar().currentMessage() == ""


def test_the_preferences_menu_opens_the_text_size_dialog(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    window = make_window(qtbot, connection)
    choose = mocker.patch(
        "omr_data_collector.ui.MainWindow.choose_text_size", return_value=None
    )
    _organization, _language, text_size, *_ = window.preferences_menu.actions()

    text_size.trigger()

    choose.assert_called_once_with(window, 0)
