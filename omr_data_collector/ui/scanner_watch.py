"""Checking the scanner folder every few minutes while the app is open.

The checks (``scanner_folder.check_folder``) run on a thread of their own, with
a database connection of their own: drawing a PDF's pages and reading sheets
take seconds, and the window must keep answering meanwhile. The result comes
back to the window's thread as the ``checked`` signal.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from omr_data_collector.i18n import tr
from omr_data_collector.scanner_folder import (
    SETTLE_SECONDS,
    FolderCheck,
    ScannerSettings,
    check_folder,
    load_scanner_settings,
)
from omr_data_collector.storage.database import database_file, open_database

if TYPE_CHECKING:
    import sqlite3

# The first check waits until the window has opened and the engine has loaded.
FIRST_CHECK_DELAY_MS = 5000
MS_PER_MINUTE = 60_000
# Files still being saved are looked at again once they've had time to settle.
SETTLE_RECHECK_MS = (SETTLE_SECONDS + 10) * 1000
# How long closing the app waits for a check to finish its current sheet.
STOP_WAIT_S = 30.0


class ScannerWatch(QObject):
    """Checks the scanner folder on a timer, and when asked (Check now).

    ``started`` says a check has begun; ``checked`` carries each check's
    ``FolderCheck`` and whether someone asked for it. Call ``start`` once the window shows, and ``stop`` when it closes.
    """

    # A check has begun, and whether someone asked for it.
    started = Signal(bool)
    checked = Signal(object, bool)
    # From the checking thread to this object's own (the window's).
    _finished = Signal(object, bool)

    def __init__(
        self, connection: sqlite3.Connection, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._database = database_file(connection)
        self.settings = ScannerSettings()
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._timed_check)
        self._soon = QTimer(self)
        self._soon.setSingleShot(True)
        self._soon.timeout.connect(self._timed_check)
        self._finished.connect(self._on_finished)

    def start(self) -> None:
        """Begin checking with the saved settings; the first check comes shortly."""
        self.apply(load_scanner_settings(), first_check_ms=FIRST_CHECK_DELAY_MS)

    def apply(self, settings: ScannerSettings, first_check_ms: int = 0) -> None:
        """Check with these settings from now on, the next check after ``first_check_ms``."""
        self.settings = settings
        self._timer.stop()
        self._soon.stop()
        if not settings.enabled:
            return
        self._timer.start(settings.check_minutes * MS_PER_MINUTE)
        self._soon.start(first_check_ms)

    @property
    def is_checking(self) -> bool:
        return self._thread is not None

    def check_now(self) -> str:
        """Check at once, as asked; "" if it started, otherwise why it didn't."""
        if not self.settings.enabled:
            return tr("No scanner folder is chosen: choose one in Preferences.")
        if self.is_checking:
            return tr("The scanner folder is being checked already.")
        self._check(asked=True)
        return ""

    def stop(self, wait_s: float = STOP_WAIT_S) -> None:
        """Stop checking: a check going on stops after its current file or sheet."""
        self._timer.stop()
        self._soon.stop()
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(wait_s)

    def _timed_check(self) -> None:
        if not self.is_checking:
            self._check(asked=False)

    def _check(self, *, asked: bool) -> None:
        self._thread = threading.Thread(
            target=self._run,
            args=(self.settings, asked),
            name="scanner-folder",
            daemon=True,
        )
        self._thread.start()
        self.started.emit(asked)

    def _run(self, settings: ScannerSettings, asked: bool) -> None:  # noqa: FBT001 (a thread's arguments)
        result = FolderCheck()
        try:
            connection = open_database(self._database)
            try:
                result = check_folder(
                    connection, settings, should_stop=self._stopping.is_set
                )
            finally:
                connection.close()
        # Whatever went wrong is reported, and the next check tries again.
        except Exception as error:
            result.problems.append(
                tr("Couldn't check the scanner folder: {error}").format(error=error)
            )
        self._finished.emit(result, asked)

    def _on_finished(self, result: FolderCheck, asked: bool) -> None:  # noqa: FBT001 (a signal's arguments)
        if self._thread is not None:
            self._thread.join()
        self._thread = None
        if self._stopping.is_set():
            return
        if result.still_saving and self.settings.enabled:
            self._soon.start(SETTLE_RECHECK_MS)
        self.checked.emit(result, asked)
