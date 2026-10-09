from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.i18n import tr
from omr_data_collector.ui.form_helpers import add_field_row

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omr_data_collector.models.Form import Form

CSV_FORMAT, JSON_FORMAT = "CSV", "JSON"
SHEET_ROWS_VISIBLE = 6


def format_labels() -> dict[str, str]:
    return {
        CSV_FORMAT: tr("CSV files: one of sheets, and one for each table"),
        JSON_FORMAT: tr("JSON: one file with everything"),
    }


class ExportDialog(QDialog):
    """Choose a form whose checked sheets to export, which ones, and the file type.

    Every checked sheet gives a row each; or chosen sheets, in the order put
    here, are combined into one (sheets that belong together, like the pages of
    one form or a log continued on further sheets).
    """

    def __init__(
        self,
        parent: QWidget | None,
        forms: Sequence[tuple[Form, int]],
        sheets: Mapping[str, Sequence[tuple[str, str]]] | None = None,
    ) -> None:
        """``forms`` are the forms with checked sheets and how many each has.

        ``sheets`` are each form's checked sheets, by form ID, as (capture ID,
        description) in the order they were added.
        """
        super().__init__(parent)
        self.setWindowTitle(tr("Export data"))
        self._sheets = sheets or {}
        self.form_combo = QComboBox()
        for form, count in forms:
            self.form_combo.addItem(
                tr("{name} (%n checked sheet(s))", None, count).format(name=form.name),
                form.form_id,
            )
        self.format_combo = QComboBox()
        for value, label in format_labels().items():
            self.format_combo.addItem(label, value)

        moves = self._build_sheet_chooser()

        form_layout = QFormLayout()
        add_field_row(form_layout, tr("&Form"), self.form_combo)
        add_field_row(form_layout, tr("File &type"), self.format_combo)
        self.note = QLabel(
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
        self.note.setWordWrap(True)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText(tr("Export…"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form_layout)
        layout.addWidget(self.every_button)
        layout.addWidget(self.chosen_button)
        layout.addWidget(self.sheet_label)
        layout.addWidget(self.sheet_list)
        layout.addWidget(moves)
        layout.addWidget(self.note)
        layout.addWidget(self.buttons)

        self.form_combo.currentIndexChanged.connect(self._fill_sheets)
        self.chosen_button.toggled.connect(self._update)
        self.sheet_list.itemChanged.connect(self._update)
        self.sheet_list.currentRowChanged.connect(self._update)
        self.move_up_button.clicked.connect(lambda: self.move_sheet(-1))
        self.move_down_button.clicked.connect(lambda: self.move_sheet(1))
        for before, after in pairwise(
            [
                self.form_combo,
                self.format_combo,
                self.every_button,
                self.chosen_button,
                self.sheet_list,
                self.move_up_button,
                self.move_down_button,
                *self.buttons.buttons(),
            ]
        ):
            QWidget.setTabOrder(before, after)
        self._fill_sheets()
        self.form_combo.setFocus(Qt.FocusReason.OtherFocusReason)

    def _build_sheet_chooser(self) -> QWidget:
        """The two ways to export, and the list of sheets to combine.

        Returns:
            The Move up and Move down buttons' row.
        """
        self.every_button = QRadioButton(tr("&Every checked sheet, a row each"))
        self.chosen_button = QRadioButton(
            tr("&Sheets I choose, combined into one, in this order")
        )
        self.every_button.setChecked(True)
        modes = QButtonGroup(self)
        modes.addButton(self.every_button)
        modes.addButton(self.chosen_button)

        self.sheet_list = QListWidget()
        self.sheet_list.setMinimumHeight(
            self.sheet_list.fontMetrics().lineSpacing() * SHEET_ROWS_VISIBLE
        )
        self.sheet_list.setAccessibleDescription(
            tr(
                "Tick the sheets to combine. They are combined in the order of "
                "this list: use Move up and Move down to change it."
            )
        )
        self.sheet_label = QLabel(tr("Sheets to combine, in &order"))
        self.sheet_label.setBuddy(self.sheet_list)
        self.move_up_button = QPushButton(tr("Move up"))
        self.move_down_button = QPushButton(tr("Move down"))
        moves = QWidget()
        moves.setAccessibleName(tr("Sheet order"))
        moves_layout = QHBoxLayout(moves)
        moves_layout.setContentsMargins(0, 0, 0, 0)
        moves_layout.addWidget(self.move_up_button)
        moves_layout.addWidget(self.move_down_button)
        moves_layout.addStretch()
        return moves

    def chosen(self) -> tuple[str, str, list[str] | None]:
        """The form's ID, the file format, and the sheets to combine.

        The sheets are capture IDs in the order to combine them, or None to
        export every checked sheet a row each.
        """
        if not self.chosen_button.isChecked():
            return self.form_combo.currentData(), self.format_combo.currentData(), None
        return (
            self.form_combo.currentData(),
            self.format_combo.currentData(),
            self._ticked(),
        )

    def move_sheet(self, offset: int) -> None:
        row = self.sheet_list.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < self.sheet_list.count():
            return
        item = self.sheet_list.takeItem(row)
        self.sheet_list.insertItem(target, item)
        self.sheet_list.setCurrentRow(target)

    def _ticked(self) -> list[str]:
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in (
                self.sheet_list.item(row) for row in range(self.sheet_list.count())
            )
            if item is not None and item.checkState() == Qt.CheckState.Checked
        ]

    def _fill_sheets(self) -> None:
        self.sheet_list.blockSignals(True)  # noqa: FBT003 (Qt API is positional)
        self.sheet_list.clear()
        for capture_id, description in self._sheets.get(
            self.form_combo.currentData(), ()
        ):
            item = QListWidgetItem(description)
            item.setData(Qt.ItemDataRole.UserRole, capture_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.sheet_list.addItem(item)
        self.sheet_list.blockSignals(False)  # noqa: FBT003
        if self.sheet_list.count():
            self.sheet_list.setCurrentRow(0)
        self._update()

    def _update(self) -> None:
        choosing = self.chosen_button.isChecked()
        for widget in (self.sheet_label, self.sheet_list):
            widget.setEnabled(choosing)
        row = self.sheet_list.currentRow()
        self.move_up_button.setEnabled(choosing and row > 0)
        self.move_down_button.setEnabled(
            choosing and 0 <= row < self.sheet_list.count() - 1
        )
        has_forms = self.form_combo.count() > 0
        self.ok_button.setEnabled(has_forms and (not choosing or bool(self._ticked())))
