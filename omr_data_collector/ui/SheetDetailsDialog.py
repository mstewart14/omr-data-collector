from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.constants import SHEET_DETAILS_PLACEMENTS
from omr_data_collector.i18n import tr
from omr_data_collector.ui.accessibility import set_field_error, style_error_label
from omr_data_collector.ui.ColumnDialog import ColumnDialog
from omr_data_collector.ui.form_helpers import add_field_row
from omr_data_collector.ui.TableBlocksPage import column_summary

if TYPE_CHECKING:
    from PySide6.QtWidgets import QLabel

    from omr_data_collector.models.SheetDetails import SheetDetails
    from omr_data_collector.models.TableBlock import Column

FIELD_ROWS_VISIBLE = 6


def placement_labels() -> dict[str, str]:
    return {
        SHEET_DETAILS_PLACEMENTS.HEADER: tr(
            "In the header, beside the QR code, on every page"
        ),
        SHEET_DETAILS_PLACEMENTS.LINE: tr("Along a line, where the block is"),
    }


def edit_field(
    parent: QWidget, field: Column | None, other_names: set[str]
) -> Column | None:
    """Open the field dialog; the new or edited field, or None if cancelled."""
    dialog = ColumnDialog(parent, field, other_names, sheet_detail=True)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.column()


class SheetDetailsDialog(QDialog):
    """Set up a sheet details block: its name and its fields, in order.

    The form keeps its own copy, so each form (and each organization) can ask
    for the details it needs.
    """

    def __init__(self, parent: QWidget | None, details: SheetDetails) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Sheet details"))
        self._details = details
        self._fields: list[Column] = list(details.fields)
        self._accepted: SheetDetails | None = None

        self.form = QFormLayout()
        self.name_edit = QLineEdit(details.name)
        self.name_edit.setToolTip(
            tr("Not printed: names the block in the form editor and the data")
        )
        self.field_list = QListWidget()
        self.field_list.setMinimumHeight(
            self.field_list.fontMetrics().lineSpacing() * FIELD_ROWS_VISIBLE
        )
        self.field_list.setAccessibleDescription(
            tr("Printed left to right along a line, wrapping when they don't fit")
        )
        self.placement_combo = QComboBox()
        for value, label in placement_labels().items():
            self.placement_combo.addItem(label, value)
        self.placement_combo.setCurrentIndex(
            max(self.placement_combo.findData(details.placement), 0)
        )
        self.field_widgets: dict[str, QWidget] = {}
        self.error_labels: dict[str, QLabel] = {}
        for key, label_text, widget in (
            ("name", tr("&Name (required)"), self.name_edit),
            ("placement", tr("&Place them"), self.placement_combo),
            ("fields", tr("&Fields (required)"), self.field_list),
        ):
            _, self.error_labels[key] = add_field_row(self.form, label_text, widget)
            self.field_widgets[key] = widget

        self.add_button = QPushButton(tr("&Add field…"))
        self.edit_button = QPushButton(tr("&Edit field…"))
        self.remove_button = QPushButton(tr("&Remove field"))
        self.move_up_button = QPushButton(tr("Move up"))
        self.move_down_button = QPushButton(tr("Move down"))
        self.field_buttons = (
            self.add_button,
            self.edit_button,
            self.remove_button,
            self.move_up_button,
            self.move_down_button,
        )
        actions = QWidget()
        actions.setAccessibleName(tr("Field actions"))
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        for button in self.field_buttons:
            actions_layout.addWidget(button)
        actions_layout.addStretch()
        self.form.addRow("", actions)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.buttons)

        self.add_button.clicked.connect(self.add_field)
        self.edit_button.clicked.connect(self.edit_selected_field)
        self.remove_button.clicked.connect(self.remove_selected_field)
        self.move_up_button.clicked.connect(lambda: self.move_selected_field(-1))
        self.move_down_button.clicked.connect(lambda: self.move_selected_field(1))
        self.field_list.itemActivated.connect(lambda _item: self.edit_selected_field())
        self.field_list.currentRowChanged.connect(self._update_buttons)
        for before, after in pairwise(
            [
                self.name_edit,
                self.placement_combo,
                self.field_list,
                *self.field_buttons,
                *self.buttons.buttons(),
            ]
        ):
            QWidget.setTabOrder(before, after)
        self._fill(0 if self._fields else -1)
        self.field_list.setFocus(Qt.FocusReason.OtherFocusReason)

    def details(self) -> SheetDetails | None:
        """The accepted details; None until OK is pressed with valid settings."""
        return self._accepted

    def add_field(self) -> None:
        field = edit_field(self, None, {field.name for field in self._fields})
        if field is not None:
            self._fields.append(field)
            self._fill(len(self._fields) - 1)

    def edit_selected_field(self) -> None:
        row = self.field_list.currentRow()
        if row < 0:
            return
        others = {
            field.name for index, field in enumerate(self._fields) if index != row
        }
        field = edit_field(self, self._fields[row], others)
        if field is not None:
            self._fields[row] = field
            self._fill(row)

    def remove_selected_field(self) -> None:
        row = self.field_list.currentRow()
        if row < 0:
            return
        del self._fields[row]
        self._fill(min(row, len(self._fields) - 1))

    def move_selected_field(self, offset: int) -> None:
        row = self.field_list.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < len(self._fields):
            return
        self._fields[row], self._fields[target] = (
            self._fields[target],
            self._fields[row],
        )
        self._fill(target)

    def accept(self) -> None:
        details = replace(
            self._details,
            name=self.name_edit.text(),
            placement=self.placement_combo.currentData(),
            fields=tuple(self._fields),
        ).normalized()
        errors = details.validation_errors(set())
        for key, label in self.error_labels.items():
            set_field_error(
                self.form, self.field_widgets[key], label, errors.get(key, "")
            )
        if errors:
            first = next(key for key in self.field_widgets if key in errors)
            self.field_widgets[first].setFocus(Qt.FocusReason.OtherFocusReason)
            return
        self._accepted = details
        super().accept()

    def _fill(self, select: int) -> None:
        self.field_list.clear()
        for field in self._fields:
            self.field_list.addItem(column_summary(field))
        if select >= 0:
            self.field_list.setCurrentRow(select)
        self._update_buttons()

    def _update_buttons(self) -> None:
        row = self.field_list.currentRow()
        self.edit_button.setEnabled(row >= 0)
        self.remove_button.setEnabled(row >= 0)
        self.move_up_button.setEnabled(row > 0)
        self.move_down_button.setEnabled(0 <= row < len(self._fields) - 1)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.PaletteChange:
            for label in self.error_labels.values():
                style_error_label(label, self.palette())
        super().changeEvent(event)
