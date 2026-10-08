from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from omr_data_collector.models.Form import Form


class OpenFormDialog(QDialog):
    """Pick a saved form to open in the editor (File > Open form)."""

    def __init__(
        self, parent: QWidget | None, forms: Sequence[Form], printed: set[str]
    ) -> None:
        """``printed`` holds the IDs of forms whose latest version has been printed."""
        super().__init__(parent)
        self.setWindowTitle("Open form")
        self.form_list = QListWidget()
        for form in forms:
            state = "printed" if form.form_id in printed else "not printed yet"
            item = QListWidgetItem(f"{form.name} (version {form.version}, {state})")
            item.setData(Qt.ItemDataRole.UserRole, form.form_id)
            self.form_list.addItem(item)
        if forms:
            self.form_list.setCurrentRow(0)
        label = QLabel("&Forms")
        label.setBuddy(self.form_list)
        self.empty_note = QLabel("No forms have been saved yet. Use File > New form.")
        self.empty_note.setVisible(not forms)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Open).setEnabled(
            bool(forms)
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.form_list.itemActivated.connect(lambda _item: self.accept())

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.form_list)
        layout.addWidget(self.empty_note)
        layout.addWidget(self.buttons)
        self.form_list.setFocus(Qt.FocusReason.OtherFocusReason)

    def chosen_form_id(self) -> str | None:
        item = self.form_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None
