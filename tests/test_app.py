from __future__ import annotations

from typing import TYPE_CHECKING

from omr_data_collector import APP_NAME, app
from omr_data_collector.ui.MainWindow import MainWindow

if TYPE_CHECKING:
    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot


def test_main_shows_main_window_and_returns_exit_code(
    qtbot: QtBot, mocker: MockerFixture
) -> None:
    # pytest-qt already owns the process's one QApplication, so main() gets a stand-in
    # whose event loop returns at once.
    application_class = mocker.patch.object(app, "QApplication")
    application_class.return_value.exec.return_value = 3

    windows: list[MainWindow] = []

    def create_window() -> MainWindow:
        window = MainWindow()
        qtbot.addWidget(window)
        windows.append(window)
        return window

    mocker.patch.object(app, "MainWindow", side_effect=create_window)

    assert app.main() == 3

    application_class.return_value.setApplicationName.assert_called_once_with(APP_NAME)
    assert len(windows) == 1
    assert windows[0].isVisible()
