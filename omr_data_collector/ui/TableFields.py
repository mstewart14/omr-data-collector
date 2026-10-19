"""A table's fields: instructions, rows, columns and a preview of it on a page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QWidget,
)

from omr_data_collector.constants import (
    ANSWER_TYPES,
    DEFAULT_TABLE_ROWS,
    MAX_TABLE_ROWS,
    PAGE_ORIENTATIONS,
    WRITTEN_DATA_TYPES,
)
from omr_data_collector.i18n import tr
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.ui.AnswerFields import date_time_format_labels
from omr_data_collector.ui.ColumnDialog import ColumnDialog
from omr_data_collector.ui.form_helpers import add_field_row, add_shortcut
from omr_data_collector.ui.FormattedTextFields import FormattedTextFields
from omr_data_collector.ui.TablePreview import (
    TablePreview,
    fit_summary,
    orientation_names,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtGui import QShortcut
    from PySide6.QtWidgets import QFormLayout

INSTRUCTIONS_VISIBLE_LINES = 3
COLUMN_ROWS_VISIBLE = 5


def edit_column(
    parent: QWidget, column: Column | None, other_names: set[str]
) -> Column | None:
    """Open the column dialog; the new or edited column, or None if cancelled."""
    dialog = ColumnDialog(parent, column, other_names)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.column()


def column_summary(column: Column) -> str:
    """One line describing a column, for the columns list and screen readers."""
    answer = column.answer
    if answer.answer_type == ANSWER_TYPES.WRITTEN:
        if answer.data_type == WRITTEN_DATA_TYPES.DATE_TIME:
            return tr("{name} (written date/time, {format})").format(
                name=column.name,
                format=date_time_format_labels()[answer.date_time_format],
            )
        count = answer.characters()
        sizes = {
            WRITTEN_DATA_TYPES.FREE_TEXT: tr(
                "{name} (written free text, %n character(s))", None, count
            ),
            WRITTEN_DATA_TYPES.NUMBER: tr(
                "{name} (written number, %n character(s))", None, count
            ),
            WRITTEN_DATA_TYPES.ID: tr(
                "{name} (written ID, %n character(s))", None, count
            ),
        }
        return sizes[answer.data_type].format(name=column.name)
    labels = ", ".join(choice.label for choice in answer.choices)
    summary = (
        tr("{name} (pick any: {choices})")
        if answer.answer_type == ANSWER_TYPES.MANY_CHOICES
        else tr("{name} (pick one: {choices})")
    )
    return summary.format(name=column.name, choices=labels)


class TableFields:
    """A table's instructions, rows, columns, and its preview on a page.

    Used by the table library and for a table written or edited on a form. Like
    ``AnswerFields`` it isn't a widget: its rows go straight into the caller's
    form, so each label stays a sibling of its control for screen readers.
    The caller's name field holds the table's name; ``table`` puts it together.
    """

    def __init__(
        self,
        form: QFormLayout,
        registry: tuple[dict[str, QWidget], dict[str, QLabel], dict[str, QLabel]],
        *,
        shortcut_parent: QWidget,
        on_change: Callable[[], None],
    ) -> None:
        """Add the rows to ``form``.

        Args:
            form: The page's or dialog's form.
            registry: Its field widgets, labels and error labels, by key; the
                instructions, rows and columns are registered under
                "instructions", "rows" and "columns".
            shortcut_parent: Where the formatting shortcuts work.
            on_change: Called whenever anything about the table changes; the
                caller then calls ``refresh`` with the table as entered.
        """
        field_widgets, field_labels, error_labels = registry
        self._parent = shortcut_parent
        self._on_change = on_change
        self._columns: list[Column] = []
        self.text_fields = FormattedTextFields(
            form,
            registry,
            key="instructions",
            text_label=tr("&Instructions"),
            style_label=tr("St&yle"),
            visible_lines=INSTRUCTIONS_VISIBLE_LINES,
            # Brief by design; the space goes to the preview instead.
            grow=False,
            shortcut_parent=shortcut_parent,
            on_change=on_change,
        )
        self.shortcuts: list[QShortcut] = list(self.text_fields.shortcuts)
        self.text_fields.editor.setPlaceholderText(
            tr("Printed above the table, like: One row per visit. Use a dark pen.")
        )

        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, MAX_TABLE_ROWS)
        self.rows_spin.setToolTip(tr("How many rows are printed for people to fill in"))
        self.fill_page_check = QCheckBox(tr("Fill to end of pa&ge"))
        self.fill_page_check.setToolTip(
            tr("Print as many rows as fit below the table on its page")
        )
        self.column_list = QListWidget()
        self.column_list.setMinimumHeight(
            self.column_list.fontMetrics().lineSpacing() * COLUMN_ROWS_VISIBLE
        )
        self.column_list.setAccessibleDescription(
            tr("Columns in printed order, left to right")
        )
        for key, label_text, widget in (
            ("rows", tr("Ro&ws"), self.rows_spin),
            ("columns", tr("C&olumns (required)"), self.column_list),
        ):
            field_labels[key], error_labels[key] = add_field_row(
                form, label_text, widget
            )
            field_widgets[key] = widget
            if key == "rows":
                form.addRow("", self.fill_page_check)

        self.add_column_button = QPushButton(tr("Add co&lumn…"))
        self.edit_column_button = QPushButton(tr("&Edit column…"))
        self.remove_column_button = QPushButton(tr("Remo&ve column"))
        self.move_left_button = QPushButton(tr("Move left"))
        self.move_right_button = QPushButton(tr("Move right"))
        self.column_buttons = (
            self.add_column_button,
            self.edit_column_button,
            self.remove_column_button,
            self.move_left_button,
            self.move_right_button,
        )
        column_actions = QWidget()
        column_actions.setAccessibleName(tr("Column actions"))
        actions_layout = QHBoxLayout(column_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        for button in self.column_buttons:
            actions_layout.addWidget(button)
        actions_layout.addStretch()
        form.addRow("", column_actions)

        self.preview_orientation_combo = QComboBox()
        for value, name in orientation_names().items():
            self.preview_orientation_combo.addItem(name, value)
        preview_label = QLabel(tr("S&how page as"))
        preview_label.setBuddy(self.preview_orientation_combo)
        form.addRow(preview_label, self.preview_orientation_combo)
        self.preview = TablePreview()
        form.addRow("", self.preview)
        self.preview_summary = QLabel()
        self.preview_summary.setWordWrap(True)
        form.addRow("", self.preview_summary)
        self._connect()

    def focus_chain(self) -> list[QWidget]:
        """The fields' controls in tab order."""
        return [
            *self.text_fields.focus_chain(),
            self.rows_spin,
            self.fill_page_check,
            self.column_list,
            *self.column_buttons,
            self.preview_orientation_combo,
        ]

    def load(
        self, table: TableBlock | None, orientation: str = PAGE_ORIENTATIONS.PORTRAIT
    ) -> None:
        """Show ``table`` (a new one's defaults if None), previewed in ``orientation``."""
        self.text_fields.set_markdown(table.instructions if table is not None else "")
        with QSignalBlocker(self.rows_spin), QSignalBlocker(self.fill_page_check):
            self.rows_spin.setValue(
                table.rows if table is not None else DEFAULT_TABLE_ROWS
            )
            self.fill_page_check.setChecked(
                table.fill_page if table is not None else False
            )
        self._columns = list(table.columns) if table is not None else []
        self._fill_column_list(0 if self._columns else -1)
        with QSignalBlocker(self.preview_orientation_combo):
            self.preview_orientation_combo.setCurrentIndex(
                self.preview_orientation_combo.findData(orientation)
            )

    def table(self, name: str, table_block_id: str) -> TableBlock:
        """The table as entered, under ``name``, normalized."""
        return TableBlock(
            name=name,
            instructions=self.text_fields.markdown(),
            rows=self.rows_spin.value(),
            fill_page=self.fill_page_check.isChecked(),
            columns=tuple(self._columns),
            table_block_id=table_block_id,
        ).normalized()

    def refresh(self, table: TableBlock, paper_size: str) -> None:
        """Bring the controls and preview up to date with ``table`` as entered."""
        # The count is kept but set aside while the table fills its page.
        self.rows_spin.setEnabled(not self.fill_page_check.isChecked())
        self._update_column_buttons()
        orientation = self.preview_orientation_combo.currentData()
        self.preview.set_table(table, paper_size, orientation)
        self.preview_summary.setText(fit_summary(table, paper_size, orientation))

    # --- Columns ------------------------------------------------------------------

    def add_column(self) -> None:
        column = edit_column(
            self._parent, None, {column.name for column in self._columns}
        )
        if column is None:
            return
        self._columns.append(column)
        self._fill_column_list(len(self._columns) - 1)
        self._on_change()

    def edit_selected_column(self) -> None:
        row = self.column_list.currentRow()
        if row < 0:
            return
        others = {
            column.name for index, column in enumerate(self._columns) if index != row
        }
        column = edit_column(self._parent, self._columns[row], others)
        if column is None:
            return
        self._columns[row] = column
        self._fill_column_list(row)
        self._on_change()

    def remove_selected_column(self) -> None:
        row = self.column_list.currentRow()
        if row < 0:
            return
        del self._columns[row]
        self._fill_column_list(min(row, len(self._columns) - 1))
        self._on_change()

    def move_selected_column(self, offset: int) -> None:
        row = self.column_list.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < len(self._columns):
            return
        self._columns[row], self._columns[target] = (
            self._columns[target],
            self._columns[row],
        )
        self._fill_column_list(target)
        self._on_change()

    def _connect(self) -> None:
        self.rows_spin.valueChanged.connect(self._on_change)
        self.fill_page_check.toggled.connect(self._on_change)
        self.add_column_button.clicked.connect(self.add_column)
        self.edit_column_button.clicked.connect(self.edit_selected_column)
        self.remove_column_button.clicked.connect(self.remove_selected_column)
        self.move_left_button.clicked.connect(lambda: self.move_selected_column(-1))
        self.move_right_button.clicked.connect(lambda: self.move_selected_column(1))
        self.column_list.itemActivated.connect(
            lambda _item: self.edit_selected_column()
        )
        self.column_list.currentRowChanged.connect(self._update_column_buttons)
        self.preview_orientation_combo.currentIndexChanged.connect(self._on_change)
        remove_shortcut = add_shortcut(
            self.column_list,
            QKeySequence.StandardKey.Delete,
            self.remove_selected_column,
        )
        # Only from the columns list: elsewhere Delete deletes the table itself.
        remove_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.shortcuts.append(remove_shortcut)

    def _fill_column_list(self, select_row: int) -> None:
        with QSignalBlocker(self.column_list):
            self.column_list.clear()
            for column in self._columns:
                self.column_list.addItem(column_summary(column))
            self.column_list.setCurrentRow(select_row)

    def _update_column_buttons(self) -> None:
        row = self.column_list.currentRow()
        selected = row >= 0
        self.edit_column_button.setEnabled(selected)
        self.remove_column_button.setEnabled(selected)
        self.move_left_button.setEnabled(row > 0)
        self.move_right_button.setEnabled(selected and row < len(self._columns) - 1)
