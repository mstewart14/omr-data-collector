from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEventLoop, QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from omr_data_collector import APP_NAME, app_version
from omr_data_collector.constants import DATABASE_FILENAME
from omr_data_collector.engine_preload import preload_engine_later
from omr_data_collector.i18n import install_translators, tr
from omr_data_collector.storage.database import open_database
from omr_data_collector.ui.app_font import (
    apply_text_size,
    remember_desktop_font,
    saved_text_size,
)
from omr_data_collector.ui.app_icon import DESKTOP_FILE_NAME, app_icon
from omr_data_collector.ui.form_helpers import warn
from omr_data_collector.ui.startup_splash import (
    show_startup_splash,
    show_step,
    starting_message,
)

# The main window and self_check bring in OpenCV and the rest of the app, so
# they're imported only once the splash window is showing. The scanning engine
# (OMRChecker and its libraries, the slowest part) loads after the window opens:
# see engine_preload.
if TYPE_CHECKING:
    from collections.abc import Callable

    from omr_data_collector.ui.MainWindow import MainWindow


def default_database_path() -> Path:
    """Where the app keeps its data: the platform's per-user app data folder.

    Call after the QApplication's name is set; Qt builds the folder from it.
    """
    data_dir = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(data_dir) / DATABASE_FILENAME


SELF_CHECK_FLAG = "--self-check"
# On a first launch the antivirus scans the new database file (Windows Defender
# does, slowly on a slow machine), and opening it fails until it's done: such
# failures are tried again for this long before they're reported.
OPEN_PATIENCE_S = 30.0
OPEN_RETRY_MS = 500


def open_app_database(
    path: Path, *, before_message: Callable[[], object] | None = None
) -> sqlite3.Connection | None:
    """Open the app's database, or say why it can't be and return None.

    An installed app has no console, so without the message it would just never
    open. A failure that can pass (the file locked or not yet readable) is tried
    again for OPEN_PATIENCE_S first; one that can't (a newer app's or damaged
    data) is reported at once. ``before_message`` runs before the message shows,
    to close the splash, which stays on top and would hide it.
    """
    give_up_at = time.monotonic() + OPEN_PATIENCE_S
    while True:
        try:
            return open_database(path)
        except (sqlite3.OperationalError, OSError) as error:
            if time.monotonic() < give_up_at:
                _wait(OPEN_RETRY_MS)
                continue
            failure: Exception = error
        except (sqlite3.Error, RuntimeError) as error:
            failure = error
        if before_message is not None:
            before_message()
        warn(
            None,
            tr("Couldn't open the app's data"),
            tr(
                "The app's data in {path} couldn't be opened, so the app can't "
                "start: {error}"
            ).format(path=path, error=failure),
            icon=QMessageBox.Icon.Critical,
        )
        return None


def _wait(milliseconds: int) -> None:
    """Pause, keeping the splash drawn."""
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def main_window_class() -> type[MainWindow]:
    """The main window's class, loading the rest of the app with it (slow)."""
    from omr_data_collector.ui.MainWindow import MainWindow  # noqa: PLC0415

    return MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(app_version())
    app.setWindowIcon(app_icon())
    app.setDesktopFileName(DESKTOP_FILE_NAME)
    install_translators(app)
    if SELF_CHECK_FLAG in sys.argv[1:2]:
        from omr_data_collector import self_check  # noqa: PLC0415

        report = sys.argv[2:3]
        return self_check.run(Path(report[0]) if report else None)

    remember_desktop_font()
    apply_text_size(saved_text_size())
    splash = show_startup_splash()
    show_step(splash, tr("Opening your data…"))
    connection = open_app_database(default_database_path(), before_message=splash.close)
    if connection is None:
        return 1
    try:
        show_step(splash, starting_message())
        window_class = main_window_class()
        show_step(splash, tr("Opening your forms…"))
        window = window_class(connection)
        window.show()
        window.start_scanner_watch()
        splash.finish(window)
        preload_engine_later()
        return app.exec()
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
