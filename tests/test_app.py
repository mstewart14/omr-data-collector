from __future__ import annotations

from typing import TYPE_CHECKING

from omr_data_collector import APP_NAME, app
from omr_data_collector.constants import DATABASE_FILENAME
from omr_data_collector.ui.MainWindow import MainWindow

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot


def test_main_shows_main_window_and_returns_exit_code(
    qtbot: QtBot, mocker: MockerFixture, tmp_path: Path
) -> None:
    # pytest-qt already owns the process's one QApplication, so main() gets a stand-in
    # whose event loop returns at once.
    application_class = mocker.patch.object(app, "QApplication")
    application_class.return_value.exec.return_value = 3
    # The real application keeps the tests' translators.
    install_translators = mocker.patch.object(app, "install_translators")
    database_path = tmp_path / "app-data" / DATABASE_FILENAME
    mocker.patch.object(app, "default_database_path", return_value=database_path)

    windows: list[MainWindow] = []

    def create_window(connection) -> MainWindow:
        window = MainWindow(connection)
        qtbot.addWidget(window)
        windows.append(window)
        return window

    mocker.patch.object(app, "MainWindow", side_effect=create_window)

    assert app.main() == 3

    application_class.return_value.setApplicationName.assert_called_once_with(APP_NAME)
    install_translators.assert_called_once_with(application_class.return_value)
    application_class.return_value.setWindowIcon.assert_called_once()
    application_class.return_value.setDesktopFileName.assert_called_once_with(
        "omr-data-collector"
    )
    assert len(windows) == 1
    assert windows[0].isVisible()
    assert database_path.exists()
