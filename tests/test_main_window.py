from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import QMessageBox

from omr_data_collector import APP_NAME, app
from omr_data_collector.app import open_app_database
from omr_data_collector.models.Organization import Organization
from omr_data_collector.storage.organization_store import (
    load_organization,
    save_organization,
)
from omr_data_collector.storage.text_block_store import list_text_blocks
from omr_data_collector.ui.MainWindow import PREFERRED_SIZE, SCREEN_SHARE, MainWindow

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot


def make_window(qtbot: QtBot, connection: sqlite3.Connection) -> MainWindow:
    window = MainWindow(connection)
    qtbot.addWidget(window)
    return window


def test_first_run_opens_on_the_organization_details(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    window = make_window(qtbot, connection)
    window.show()

    assert window.isVisible()
    assert window.windowTitle() == f"Organization details - {APP_NAME}"
    assert window.stack.currentWidget() is window.organization_page


def test_opens_on_the_form_editor_once_the_organization_is_entered(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    save_organization(connection, Organization(name="Food Bank"))

    window = make_window(qtbot, connection)

    assert window.stack.currentWidget() is window.forms_page
    assert window.windowTitle() == f"Form editor - {APP_NAME}"


def test_there_is_no_sections_list_taking_up_room(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    window = make_window(qtbot, connection)

    assert window.centralWidget() is window.stack


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
    question = mocker.patch("omr_data_collector.ui.MainWindow.ask_save_discard_cancel")
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
    mocker.patch(
        "omr_data_collector.ui.MainWindow.ask_save_discard_cancel", return_value=answer
    )
    event = QCloseEvent()

    window.closeEvent(event)

    assert event.isAccepted() == closes
    assert (load_organization(connection) is not None) == saved


def test_stays_open_when_saving_on_close_fails(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    window = make_window(qtbot, connection)
    window.organization_page.email_edit.setText("not an email")
    mocker.patch(
        "omr_data_collector.ui.MainWindow.ask_save_discard_cancel",
        return_value=QMessageBox.StandardButton.Save,
    )
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()


def test_opening_a_section_titles_the_window(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    window = make_window(qtbot, connection)

    window.open_section(1)

    assert window.stack.currentWidget() is window.text_blocks_page
    assert window.windowTitle() == f"Text blocks - {APP_NAME}"


def test_ctrl_number_opens_a_section_and_focuses_its_first_control(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    window = make_window(qtbot, connection)
    with qtbot.waitActive(window):
        window.show()
        window.activateWindow()

    qtbot.keyClick(window, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    assert window.stack.currentWidget() is window.text_blocks_page
    assert window.focusWidget() is window.text_blocks_page.item_list

    qtbot.keyClick(window, Qt.Key.Key_5, Qt.KeyboardModifier.ControlModifier)
    assert window.focusWidget() is window.organization_page.name_edit

    qtbot.keyClick(window, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    assert window.stack.currentWidget() is window.forms_page
    assert window.focusWidget() is window.forms_page.block_list


def test_unsaved_changes_survive_switching_sections(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    window = make_window(qtbot, connection)
    window.organization_page.name_edit.setText("Food Bank")
    # pytest-qt closes the window afterwards; answer its unsaved-changes question.
    mocker.patch(
        "omr_data_collector.ui.MainWindow.ask_save_discard_cancel",
        return_value=QMessageBox.StandardButton.Discard,
    )

    window.open_section(1)
    window.open_section(0)

    assert window.organization_page.name_edit.text() == "Food Bank"


def test_close_saves_every_page_with_changes(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    window = make_window(qtbot, connection)
    window.organization_page.name_edit.setText("Food Bank")
    window.text_blocks_page.name_edit.setText("Footer")
    window.text_blocks_page.text_fields.editor.setPlainText("Thanks")
    question = mocker.patch(
        "omr_data_collector.ui.MainWindow.ask_save_discard_cancel",
        return_value=QMessageBox.StandardButton.Save,
    )
    event = QCloseEvent()

    window.closeEvent(event)

    assert "Text blocks and Organization details" in question.call_args.args[1]
    assert event.isAccepted()
    assert load_organization(connection) is not None
    assert [block.name for block in list_text_blocks(connection)] == ["Footer"]


def test_close_stays_on_the_page_whose_save_failed(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    window = make_window(qtbot, connection)
    window.text_blocks_page.name_edit.setText("Footer")  # no text, so can't save
    mocker.patch(
        "omr_data_collector.ui.MainWindow.ask_save_discard_cancel",
        return_value=QMessageBox.StandardButton.Save,
    )
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
    assert window.stack.currentWidget() is window.text_blocks_page


def test_the_window_fits_a_small_screen(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry().size()

    window = make_window(qtbot, connection)

    assert window.size() == PREFERRED_SIZE.boundedTo(available * SCREEN_SHARE)


def test_a_database_that_cant_be_opened_is_explained(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    critical = mocker.patch("omr_data_collector.app.warn")
    newer = tmp_path / "newer.sqlite3"
    sqlite3.connect(newer).execute("PRAGMA user_version = 999").connection.close()

    assert open_app_database(newer) is None

    (_, title, message), options = critical.call_args
    assert title == "Couldn't open the app's data"
    assert "newer version of the app" in message
    assert options["icon"] == QMessageBox.Icon.Critical


def test_a_database_that_cant_open_yet_is_tried_again(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    # A first launch on Windows: the antivirus holds the new file for a moment.
    real_open = app.open_database
    attempts = mocker.patch.object(
        app,
        "open_database",
        side_effect=[
            sqlite3.OperationalError("database is locked"),
            OSError("in use"),
            real_open(tmp_path / "data.sqlite3"),
        ],
    )
    mocker.patch.object(app, "OPEN_RETRY_MS", 1)
    critical = mocker.patch("omr_data_collector.app.warn")

    connection = open_app_database(tmp_path / "data.sqlite3")

    assert connection is not None
    connection.close()
    assert attempts.call_count == 3
    critical.assert_not_called()


def test_a_database_that_stays_locked_is_reported_after_the_splash_closes(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    mocker.patch.object(
        app, "open_database", side_effect=sqlite3.OperationalError("locked")
    )
    mocker.patch.object(app, "OPEN_PATIENCE_S", 0.05)
    mocker.patch.object(app, "OPEN_RETRY_MS", 1)
    order: list[str] = []
    mocker.patch(
        "omr_data_collector.app.warn", side_effect=lambda *_, **__: order.append("warn")
    )

    result = open_app_database(
        tmp_path / "data.sqlite3", before_message=lambda: order.append("close")
    )

    assert result is None
    assert order == ["close", "warn"]


def test_a_newer_apps_database_is_reported_without_waiting(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    newer = tmp_path / "newer.sqlite3"
    sqlite3.connect(newer).execute("PRAGMA user_version = 999").connection.close()
    wait = mocker.patch.object(app, "_wait")
    mocker.patch("omr_data_collector.app.warn")

    assert open_app_database(newer) is None
    wait.assert_not_called()
