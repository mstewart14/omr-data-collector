"""Preferences > About: the version, and links to the source code and its issues."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

from omr_data_collector import ISSUES_URL, REPOSITORY_URL, app_version
from omr_data_collector.ui.AboutDialog import AboutDialog
from omr_data_collector.ui.MainWindow import MainWindow

if TYPE_CHECKING:
    import sqlite3

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot


def test_the_version_is_the_installed_packages() -> None:
    project = __import__("tomllib").loads(
        (__import__("pathlib").Path(__file__).parents[1] / "pyproject.toml").read_text()
    )["project"]["version"]

    assert app_version() == project


def test_about_shows_the_version_and_links(qtbot: QtBot) -> None:
    dialog = AboutDialog(None, "1.2.3")
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "About OMR Data Collector"
    assert dialog.version_label.text() == "Version 1.2.3"
    assert f'href="{REPOSITORY_URL}"' in dialog.source_link.text()
    assert f'href="{ISSUES_URL}"' in dialog.issues_link.text()
    assert ISSUES_URL == "https://github.com/mstewart14/omr-data-collector/issues"


def test_the_links_open_in_the_browser_and_work_from_the_keyboard(
    qtbot: QtBot,
) -> None:
    dialog = AboutDialog(None, "1.2.3")
    qtbot.addWidget(dialog)

    for link, name in (
        (dialog.source_link, "Source code on GitHub"),
        (dialog.issues_link, "Report a problem or suggest an idea"),
    ):
        assert link.openExternalLinks()
        assert link.textInteractionFlags() & (
            Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        assert link.focusPolicy() == Qt.FocusPolicy.StrongFocus
        assert link.accessibleName() == name
    assert dialog.source_link.nextInFocusChain() is dialog.issues_link


def test_an_unrecorded_version_says_so(qtbot: QtBot) -> None:
    dialog = AboutDialog(None, "")
    qtbot.addWidget(dialog)

    assert dialog.version_label.text() == "Version unknown"


def test_about_is_in_the_preferences_menu(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    window = MainWindow(connection)
    qtbot.addWidget(window)
    shown = mocker.patch.object(AboutDialog, "exec")
    action = next(
        action
        for action in window.preferences_menu.actions()
        if action.text() == "&About OMR Data Collector…"
    )

    assert action.menuRole() == QAction.MenuRole.AboutRole
    action.trigger()
    shown.assert_called_once()
