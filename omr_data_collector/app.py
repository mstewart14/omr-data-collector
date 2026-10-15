from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from omr_data_collector import APP_NAME, app_version, self_check
from omr_data_collector.constants import DATABASE_FILENAME
from omr_data_collector.i18n import install_translators, tr
from omr_data_collector.storage.database import open_database
from omr_data_collector.ui.app_icon import DESKTOP_FILE_NAME, app_icon
from omr_data_collector.ui.form_helpers import warn
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


def open_app_database(path: Path) -> sqlite3.Connection | None:
    """Open the app's database, or say why it can't be and return None.

    An installed app has no console, so without the message it would just never
    open.
    """
    try:
        return open_database(path)
    except (sqlite3.Error, OSError, RuntimeError) as error:
        warn(
            None,
            tr("Couldn't open the app's data"),
            tr(
                "The app's data in {path} couldn't be opened, so the app can't "
                "start: {error}"
            ).format(path=path, error=error),
            icon=QMessageBox.Icon.Critical,
        )
        return None


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(app_version())
    app.setWindowIcon(app_icon())
    app.setDesktopFileName(DESKTOP_FILE_NAME)
    install_translators(app)
    if SELF_CHECK_FLAG in sys.argv[1:2]:
        report = sys.argv[2:3]
        return self_check.run(Path(report[0]) if report else None)

    connection = open_app_database(default_database_path())
    if connection is None:
        return 1
    try:
        window = MainWindow(connection)
        window.show()
        return app.exec()
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
