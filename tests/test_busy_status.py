"""The status bar's sign of background work: the engine loading, scanner checks."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest
from PySide6.QtWidgets import QWidget

from omr_data_collector.scanner_folder import FolderCheck, ScannerSettings
from omr_data_collector.ui.busy_status import BusyStatus, SweepBar
from omr_data_collector.ui.MainWindow import MainWindow

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.usefixtures("qapp")


def test_the_newest_work_is_named_until_all_of_it_is_done(qtbot: QtBot) -> None:
    holder = QWidget()
    qtbot.addWidget(holder)
    busy = BusyStatus(holder)
    holder.show()
    assert not busy.isVisible()

    busy.begin("engine", "Loading…")
    busy.begin("scanner", "Checking…")

    assert busy.isVisible()
    assert busy.text == "Checking…"
    assert busy.bar.maximum() == 0  # moving, with no end known
    assert busy.bar.accessibleName() == "Working"
    assert busy.bar.accessibleDescription() == "Checking…"
    busy.end("scanner")
    assert busy.text == "Loading…"
    busy.end("engine")
    busy.end("engine")  # ending twice does no harm
    assert not busy.isVisible()
    assert busy.text == ""


def test_the_window_shows_the_engine_loading_until_it_has(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    window = MainWindow(connection)
    qtbot.addWidget(window)
    window.show()

    loaded = window.show_engine_loading()

    assert window.busy.isVisible()
    assert window.busy.text == "Loading the reading engine…"
    # The loading thread says when it's done.
    threading.Thread(target=loaded).start()
    qtbot.waitUntil(lambda: not window.busy.isVisible())


def test_the_window_shows_a_scanner_check_while_it_goes_on(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    window = MainWindow(connection)
    qtbot.addWidget(window)
    window.show()

    window.scanner_watch.started.emit(False)  # noqa: FBT003 (a signal's argument)
    assert window.busy.text == "Checking the scanner folder…"
    window.scanner_watch.checked.emit(FolderCheck(), False)  # noqa: FBT003
    assert not window.busy.isVisible()


def test_the_bar_slides_while_shown_and_stops_when_hidden(qtbot: QtBot) -> None:
    bar = SweepBar()
    qtbot.addWidget(bar)
    bar.resize(100, 20)
    bar.show()
    start = bar.block_rect()

    qtbot.waitUntil(lambda: bar.block_rect() != start)

    assert bar.is_moving
    assert bar.maximum() == 0  # a progress bar with no end known, to screen readers
    bar.hide()
    assert not bar.is_moving


def test_the_window_shows_scans_waiting_to_finish_saving(
    qtbot: QtBot, connection: sqlite3.Connection, tmp_path: Path
) -> None:
    window = MainWindow(connection)
    qtbot.addWidget(window)
    window.show()
    window.scanner_watch.apply(ScannerSettings(str(tmp_path)), first_check_ms=60_000)

    window.scanner_watch.checked.emit(FolderCheck(still_saving=2), False)  # noqa: FBT003

    assert window.busy.text == "Waiting for 2 scans to finish saving…"
    # The check a minute later takes them.
    window.scanner_watch.started.emit(False)  # noqa: FBT003
    assert window.busy.text == "Checking the scanner folder…"
    window.scanner_watch.checked.emit(FolderCheck(), False)  # noqa: FBT003
    assert not window.busy.isVisible()
    window.scanner_watch.stop()
