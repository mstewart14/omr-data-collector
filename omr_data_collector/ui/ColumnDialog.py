from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.constants import ANSWER_TYPES
from omr_data_collector.i18n import tr
from omr_data_collector.models.AnswerSpec import AnswerSpec
from omr_data_collector.models.TableBlock import Column
from omr_data_collector.ui.accessibility import show_field_errors, style_error_label
from omr_data_collector.ui.AnswerFields import AnswerFields
from omr_data_collector.ui.form_helpers import (
    add_field_row,
    finish_editing,
    ok_cancel_buttons,
)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QLabel


class ColumnDialog(QDialog):
    """Add or edit one column of a table block (wiki stories 30002-30006).

    A dialog rather than more rows on the table page: a column's settings would
    leave the page too few unique Alt+letter mnemonics, and the column's errors
    stay together until it's right.
    """

    def __init__(
        self,
        parent: QWidget | None,
        column: Column | None,
        other_names: set[str],
        *,
        sheet_detail: bool = False,
    ) -> None:
        """Edit ``column``, or a new one when it's None.

        ``other_names`` are the table's other column names, which this one may not
        repeat. With ``sheet_detail`` it edits a field of a sheet details block
        instead, which has a label but no example.
        """
        super().__init__(parent)
        self._sheet_detail = sheet_detail
        if sheet_detail:
            self.setWindowTitle(tr("Edit field") if column else tr("Add field"))
        else:
            self.setWindowTitle(tr("Edit column") if column else tr("Add column"))
        self._other_names = other_names
        self._column: Column | None = None

        self.form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setToolTip(
            tr("Printed as the field's label, and the export column name")
            if sheet_detail
            else tr("Printed as the heading, and the export column name")
        )
        self.example_edit = QLineEdit()
        self.example_edit.setPlaceholderText(
            tr("Printed under the heading, like: 2026-10-08")
        )
        self.field_widgets: dict[str, QWidget] = {}
        self.field_labels: dict[str, QLabel] = {}
        self.error_labels: dict[str, QLabel] = {}
        for key, label_text, widget in (
            (
                "name",
                tr("Field &name (required)")
                if sheet_detail
                else tr("Column &name (required)"),
                self.name_edit,
            ),
            ("example", tr("&Example"), self.example_edit),
        ):
            self.field_labels[key], self.error_labels[key] = add_field_row(
                self.form, label_text, widget
            )
            self.field_widgets[key] = widget
        self.wrap_check = QCheckBox(tr("Wrap a &long heading"))
        self.wrap_check.setChecked(True)
        self.wrap_check.setToolTip(
            tr(
                "Let the heading take up to three lines, so the column needn't be "
                "as wide as its name"
            )
        )
        self.form.addRow("", self.wrap_check)
        self.answer_fields = AnswerFields(
            self.form,
            self.field_widgets,
            self.field_labels,
            self.error_labels,
            lambda: None,
        )

        self.buttons = ok_cancel_buttons(self)

        # A sheet detail's label says it all: no example is printed, and its
        # label is on one line beside its answer.
        self.form.setRowVisible(self.example_edit, not sheet_detail)
        self.form.setRowVisible(self.wrap_check, not sheet_detail)

        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.buttons)

        focus_chain = [
            self.name_edit,
            self.example_edit,
            self.wrap_check,
            *self.answer_fields.focus_chain(),
            *self.buttons.buttons(),
        ]
        for before, after in pairwise(focus_chain):
            QWidget.setTabOrder(before, after)

        if column is not None:
            self.name_edit.setText(column.name)
            self.example_edit.setText(column.example)
            self.wrap_check.setChecked(column.wrap_heading)
            self.answer_fields.set_spec(column.answer)
        else:
            self.answer_fields.set_spec(AnswerSpec.default(ANSWER_TYPES.YES_NO))
        self.name_edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def entered_column(self) -> Column:
        """The column as currently entered, normalized."""
        return Column(
            name=self.name_edit.text(),
            example=self.example_edit.text(),
            answer=self.answer_fields.spec(),
            wrap_heading=self.wrap_check.isChecked() or self._sheet_detail,
        ).normalized()

    def column(self) -> Column | None:
        """The accepted column; None until OK is pressed with valid settings."""
        return self._column

    def accept(self) -> None:
        finish_editing(self)
        column = self.entered_column()
        errors = column.validation_errors(self._other_names)
        if self._sheet_detail and column.name.casefold() in {
            name.casefold() for name in self._other_names
        }:
            errors["name"] = tr(
                'These sheet details already have a field called "{name}".'
            ).format(name=column.name)
        # Stays open, on the first problem.
        if show_field_errors(self.form, self.field_widgets, self.error_labels, errors):
            return
        self._column = column
        super().accept()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.PaletteChange:
            for label in self.error_labels.values():
                style_error_label(label, self.palette())
        super().changeEvent(event)
