from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.i18n import tr
from omr_data_collector.ui.form_helpers import add_field_row

if TYPE_CHECKING:
    from collections.abc import Sequence

    from omr_data_collector.models.Form import Form

CSV_FORMAT, JSON_FORMAT = "CSV", "JSON"


def format_labels() -> dict[str, str]:
    return {
        CSV_FORMAT: tr("CSV files: one of sheets, and one for each table"),
        JSON_FORMAT: tr("JSON: one file with everything"),
    }


class ExportDialog(QDialog):
    """Choose a form whose checked sheets to export, and the kind of file."""

    def __init__(
        self, parent: QWidget | None, forms: Sequence[tuple[Form, int]]
    ) -> None:
        """``forms`` are the forms with checked sheets, and how many each has."""
        super().__init__(parent)
        self.setWindowTitle(tr("Export data"))
        self.form_combo = QComboBox()
        for form, count in forms:
            self.form_combo.addItem(
                tr("{name} (%n checked sheet(s))", None, count).format(name=form.name),
                form.form_id,
            )
        self.format_combo = QComboBox()
        for value, label in format_labels().items():
            self.format_combo.addItem(label, value)

        form_layout = QFormLayout()
        add_field_row(form_layout, tr("&Form"), self.form_combo)
        add_field_row(form_layout, tr("File &type"), self.format_combo)
        note = QLabel(
            tr(
                "Only sheets saved on the Capture screen are exported: not ones "
                "rejected or still to check."
            )
            if forms
            else tr(
                "No sheets have been checked and saved yet. Check them on the "
                "Capture screen first."
            )
        )
        note.setWordWrap(True)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setText(tr("Export…"))
        ok_button.setEnabled(bool(forms))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form_layout)
        layout.addWidget(note)
        layout.addWidget(self.buttons)
        self.form_combo.setFocus(Qt.FocusReason.OtherFocusReason)

    def chosen(self) -> tuple[str, str]:
        """The chosen form's ID and the file format."""
        return self.form_combo.currentData(), self.format_combo.currentData()
