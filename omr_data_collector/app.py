from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

from omr_data_collector import APP_NAME
from omr_data_collector.constants import DATABASE_FILENAME
from omr_data_collector.storage.database import open_database
from omr_data_collector.ui.MainWindow import MainWindow


def default_database_path() -> Path:
    """Where the app keeps its data: the platform's per-user app data folder.

    Call after the QApplication's name is set; Qt builds the folder from it.
    """
    data_dir = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(data_dir) / DATABASE_FILENAME


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    connection = open_database(default_database_path())
    try:
        window = MainWindow(connection)
        window.show()
        return app.exec()
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
