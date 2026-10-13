from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

from omr_data_collector import APP_NAME, self_check
from omr_data_collector.constants import DATABASE_FILENAME
from omr_data_collector.i18n import install_translators
from omr_data_collector.storage.database import open_database
from omr_data_collector.ui.app_icon import DESKTOP_FILE_NAME, app_icon
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


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setDesktopFileName(DESKTOP_FILE_NAME)
    install_translators(app)
    if SELF_CHECK_FLAG in sys.argv[1:2]:
        report = sys.argv[2:3]
        return self_check.run(Path(report[0]) if report else None)

    connection = open_database(default_database_path())
    try:
        window = MainWindow(connection)
        window.show()
        return app.exec()
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
