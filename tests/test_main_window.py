from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from omr_data_collector import APP_NAME
from omr_data_collector.storage.organization_store import load_organization
from omr_data_collector.ui.MainWindow import MainWindow

if TYPE_CHECKING:
    import sqlite3

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot


def make_window(qtbot: QtBot, connection: sqlite3.Connection) -> MainWindow:
    window = MainWindow(connection)
    qtbot.addWidget(window)
    return window


def test_main_window_opens_on_the_organization_page(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    window = make_window(qtbot, connection)
    window.show()

    assert window.isVisible()
    assert window.windowTitle() == APP_NAME
    assert window.centralWidget() is window.organization_page


def test_page_status_messages_show_in_the_status_bar(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    window = make_window(qtbot, connection)

    window.organization_page.status_message.emit("Organization saved.")

    assert window.statusBar().currentMessage() == "Organization saved."


def test_closes_without_asking_when_nothing_changed(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    window = make_window(qtbot, connection)
    question = mocker.patch.object(QMessageBox, "question")
    event = QCloseEvent()

    window.closeEvent(event)

    question.assert_not_called()
    assert event.isAccepted()


# Each answer, with whether the window then closes and whether the changes are saved.
CLOSE_ANSWERS = {
    QMessageBox.StandardButton.Save: (True, True),
    QMessageBox.StandardButton.Discard: (True, False),
    QMessageBox.StandardButton.Cancel: (False, False),
}


@pytest.mark.parametrize("answer", CLOSE_ANSWERS)
def test_asks_about_unsaved_changes_on_close(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    answer: QMessageBox.StandardButton,
) -> None:
    closes, saved = CLOSE_ANSWERS[answer]
    window = make_window(qtbot, connection)
    window.organization_page.name_edit.setText("Food Bank")
    mocker.patch.object(QMessageBox, "question", return_value=answer)
    event = QCloseEvent()

    window.closeEvent(event)

    assert event.isAccepted() == closes
    assert (load_organization(connection) is not None) == saved


def test_stays_open_when_saving_on_close_fails(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    window = make_window(qtbot, connection)
    window.organization_page.email_edit.setText("not an email")
    mocker.patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Save
    )
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
