from __future__ import annotations

from typing import TYPE_CHECKING

from omr_data_collector import APP_NAME
from omr_data_collector.ui.MainWindow import MainWindow

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


def test_main_window_opens(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    assert window.isVisible()
    assert window.windowTitle() == APP_NAME
