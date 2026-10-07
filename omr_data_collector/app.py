from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from omr_data_collector import APP_NAME
from omr_data_collector.ui.MainWindow import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
