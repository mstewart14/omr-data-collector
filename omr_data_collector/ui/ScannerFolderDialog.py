"""Preferences > Scanner folder: where a scanner saves its scans (wiki 60011)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.i18n import tr
from omr_data_collector.scanner_folder import (
    MAX_CHECK_MINUTES,
    MIN_CHECK_MINUTES,
    ScannerSettings,
    added_folder_name,
    failed_folder_name,
)
from omr_data_collector.ui.accessibility import show_field_errors
from omr_data_collector.ui.form_helpers import add_field_row, ok_cancel_buttons


def choose_folder(parent: QWidget, start: str) -> str:
    """Ask which folder the scanner saves into; "" if cancelled."""
    return QFileDialog.getExistingDirectory(
        parent, tr("Choose the scanner folder"), start
    )


class ScannerFolderDialog(QDialog):
    """Choose the scanner folder, how often it's checked, and whether to read.

    A blank folder turns the scanner folder off.
    """

    def __init__(self, parent: QWidget | None, current: ScannerSettings) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Scanner folder"))
        self.folder_edit = QLineEdit(current.folder)
        self.folder_edit.setPlaceholderText(tr("None: scans are added by hand"))
        self.browse_button = QPushButton(tr("&Browse…"))
        self.browse_button.setAccessibleDescription(
            tr("Choose the scanner folder from the folders on this computer")
        )
        self.browse_button.clicked.connect(self.browse)
        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(MIN_CHECK_MINUTES, MAX_CHECK_MINUTES)
        self.minutes_spin.setValue(current.check_minutes)
        self.read_check = QCheckBox(tr("&Read new scans as soon as they're added"))
        self.read_check.setChecked(current.read_automatically)

        self.form = QFormLayout()
        _, folder_error = add_field_row(
            self.form, tr("Scanner &folder"), self.folder_edit
        )
        # A row of its own: wrapped together with the field, the label would no
        # longer name the field for screen readers.
        self.form.addRow("", self.browse_button)
        add_field_row(self.form, tr("Check &every (minutes)"), self.minutes_spin)
        self.form.addRow("", self.read_check)
        self._error_labels = {"folder": folder_error}

        note = QLabel(
            tr(
                "While the app is open, new pictures and PDFs the scanner saves "
                "in this folder are added as sheets. Each file is then moved into "
                'the folder\'s "{added}" folder, or "{failed}" if it can\'t be '
                "added, so it's only taken once. Use one scanner folder per "
                "computer."
            ).format(added=added_folder_name(), failed=failed_folder_name())
        )
        note.setWordWrap(True)
        self.buttons = ok_cancel_buttons(self)

        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(note)
        layout.addWidget(self.buttons)
        QWidget.setTabOrder(self.folder_edit, self.browse_button)
        QWidget.setTabOrder(self.browse_button, self.minutes_spin)
        QWidget.setTabOrder(self.minutes_spin, self.read_check)
        self.folder_edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def browse(self) -> None:
        folder = choose_folder(self, self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)

    def accept(self) -> None:
        folder = self.folder_edit.text().strip()
        errors = {}
        if folder and not Path(folder).is_dir():
            errors["folder"] = tr(
                "There's no folder {folder}. Choose one that exists, or leave it "
                "blank for none."
            ).format(folder=folder)
        if show_field_errors(
            self.form, {"folder": self.folder_edit}, self._error_labels, errors
        ):
            return
        super().accept()

    def chosen_settings(self) -> ScannerSettings:
        return ScannerSettings(
            folder=self.folder_edit.text().strip(),
            check_minutes=self.minutes_spin.value(),
            read_automatically=self.read_check.isChecked(),
        )
