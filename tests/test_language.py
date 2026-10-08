"""Preferences > Language: choosing the app's language for the next start."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QLabel

from omr_data_collector import i18n
from omr_data_collector.i18n import (
    LANGUAGE_VARIABLE,
    chosen_locale,
    language_choices,
    save_language,
    saved_language,
)
from omr_data_collector.ui.LanguageDialog import LanguageDialog
from omr_data_collector.ui.MainWindow import MainWindow

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot


@pytest.fixture(autouse=True)
def no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LANGUAGE_VARIABLE, raising=False)


def test_the_system_language_is_the_default() -> None:
    assert saved_language() == ""
    assert chosen_locale().name() == QLocale.system().name()


def test_a_saved_language_is_used_from_the_next_start() -> None:
    save_language("fr_CA")

    assert saved_language() == "fr_CA"
    assert chosen_locale().language() == QLocale.Language.French


def test_the_override_variable_beats_the_saved_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_language("fr")
    monkeypatch.setenv(LANGUAGE_VARIABLE, "de")

    assert chosen_locale().language() == QLocale.Language.German


def test_choices_start_with_the_system_language_then_name_each_in_itself() -> None:
    choices = language_choices()

    code, name = choices[0]
    assert code == ""
    assert name.startswith("System language (")
    assert ("en", "English") in choices


def test_the_dialog_starts_on_the_current_language(qtbot: QtBot) -> None:
    dialog = LanguageDialog(None, "en")
    qtbot.addWidget(dialog)

    assert dialog.chosen_language() == "en"

    dialog.language_combo.setCurrentIndex(0)

    assert dialog.chosen_language() == ""


def test_the_dialog_labels_its_list_for_screen_readers(qtbot: QtBot) -> None:
    dialog = LanguageDialog(None, "")
    qtbot.addWidget(dialog)

    (label,) = [
        label
        for label in dialog.findChildren(QLabel)
        if label.buddy() is dialog.language_combo
    ]

    assert label.text() == "&Language"


def make_window(qtbot: QtBot, connection: sqlite3.Connection) -> MainWindow:
    window = MainWindow(connection)
    qtbot.addWidget(window)
    return window


def test_choosing_a_language_saves_it_and_says_when_it_applies(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    window = make_window(qtbot, connection)
    mocker.patch("omr_data_collector.ui.MainWindow.choose_language", return_value="en")
    announce = mocker.patch("omr_data_collector.ui.MainWindow.announce")

    window.change_language()

    assert saved_language() == "en"
    announce.assert_called_once_with(
        window, "The app will be in English the next time it starts."
    )


def test_going_back_to_the_system_language(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_language("en")
    window = make_window(qtbot, connection)
    mocker.patch("omr_data_collector.ui.MainWindow.choose_language", return_value="")

    window.change_language()

    assert saved_language() == ""
    assert "follow the system language" in window.statusBar().currentMessage()


@pytest.mark.parametrize("answer", [None, ""], ids=["cancelled", "unchanged"])
def test_cancelling_or_keeping_the_language_changes_nothing(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    answer: str | None,
) -> None:
    window = make_window(qtbot, connection)
    mocker.patch(
        "omr_data_collector.ui.MainWindow.choose_language", return_value=answer
    )
    save = mocker.patch("omr_data_collector.ui.MainWindow.save_language")

    window.change_language()

    save.assert_not_called()
    assert window.statusBar().currentMessage() == ""


def test_the_preferences_menu_opens_the_language_dialog(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    window = make_window(qtbot, connection)
    choose = mocker.patch(
        "omr_data_collector.ui.MainWindow.choose_language", return_value=None
    )
    _organization, language = window.preferences_menu.actions()

    language.trigger()

    choose.assert_called_once_with(window, "")


def test_a_new_language_is_named_by_its_translators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = tmp_path / "omr_data_collector_fr.ts"
    catalog.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<TS version="2.1" language="fr" sourcelanguage="en"><context><name></name>'
        "<message><source>English</source>"
        "<comment>the name of this language, in this language</comment>"
        "<translation>Français</translation></message>"
        "</context></TS>\n",
        encoding="utf-8",
    )
    subprocess.run(  # noqa: S603
        ["pyside6-lrelease", "-silent", str(catalog)],  # noqa: S607
        check=True,
    )
    monkeypatch.setattr(i18n, "TRANSLATIONS_DIR", tmp_path)

    assert i18n.available_languages() == ["fr"]
    assert ("fr", "Français") in language_choices()
