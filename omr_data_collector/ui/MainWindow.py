from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMainWindow, QMessageBox

from omr_data_collector import APP_NAME
from omr_data_collector.ui.accessibility import announce
from omr_data_collector.ui.OrganizationPage import OrganizationPage

if TYPE_CHECKING:
    import sqlite3

    from PySide6.QtGui import QCloseEvent

STATUS_MESSAGE_TIMEOUT_MS = 5000


class MainWindow(QMainWindow):
    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 800)

        # The only page so far; navigation between pages arrives with the form
        # builder.
        self.organization_page = OrganizationPage(connection)
        self.organization_page.status_message.connect(self.show_status)
        self.setCentralWidget(self.organization_page)

    def show_status(self, message: str) -> None:
        """Show a message in the status bar and have screen readers speak it.

        Screen readers don't watch the status bar, so without the announcement a
        result like "Organization saved." would go unheard.
        """
        self.statusBar().showMessage(message, STATUS_MESSAGE_TIMEOUT_MS)
        announce(self, message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt override)
        if not self.organization_page.has_unsaved_changes():
            event.accept()
            return
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            "Save your changes to the organization before closing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            self.organization_page.save()
            # Saving fails, leaving the changes, when a field is invalid; stay open
            # so the errors can be fixed.
            if self.organization_page.has_unsaved_changes():
                event.ignore()
                return
        elif answer == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return
        event.accept()
