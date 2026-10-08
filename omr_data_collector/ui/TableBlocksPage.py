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
    PAPER_SIZES,
    WRITTEN_DATA_TYPES,
)
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.storage.organization_store import load_organization
from omr_data_collector.storage.table_block_store import (
    delete_table_block,
    list_table_blocks,
    save_table_block,
)
from omr_data_collector.ui.AnswerFields import DATA_TYPE_LABELS
from omr_data_collector.ui.ColumnDialog import ColumnDialog
from omr_data_collector.ui.form_helpers import add_field_row, add_shortcut
from omr_data_collector.ui.FormattedTextFields import FormattedTextFields
from omr_data_collector.ui.LibraryPage import LibraryPage
from omr_data_collector.ui.TablePreview import (
    ORIENTATION_NAMES,
    TablePreview,
    fit_summary,
)

if TYPE_CHECKING:
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
        kind = DATA_TYPE_LABELS[answer.data_type].lower()
        if answer.data_type == WRITTEN_DATA_TYPES.DATE_TIME:
            detail = f"written {kind}, {answer.date_time_format}"
        else:
            detail = f"written {kind}, {answer.characters()} characters"
    else:
        labels = ", ".join(choice.label for choice in answer.choices)
        how = (
            "pick any"
            if answer.answer_type == ANSWER_TYPES.MANY_CHOICES
            else "pick one"
        )
        detail = f"{how}: {labels}"
    return f"{column.name} ({detail})"


class TableBlocksPage(LibraryPage):
    """Create, save, edit, duplicate and delete reusable tables.

    Covers the "Create reusable data input table data collector block" epic on
    the wiki (stories 30001-30010), including previewing the table on a portrait
    or landscape page.
    """

    NOUN = "table"
    LIST_LABEL = "Table li&brary"
    NAME_LABEL = "Na&me (required)"
    NEW_HINT = "Enter a name, then add columns."

    def build_fields(self, form: QFormLayout) -> list[QWidget]:
        self._columns: list[Column] = []
        self.text_fields = FormattedTextFields(
            form,
            (self.field_widgets, self.field_labels, self.error_labels),
            key="instructions",
            text_label="&Instructions",
            style_label="St&yle",
            visible_lines=INSTRUCTIONS_VISIBLE_LINES,
            # Brief by design; the space goes to the preview instead.
            grow=False,
            shortcut_parent=self,
            on_change=self.update_state,
        )
        self.shortcuts += self.text_fields.shortcuts
        self.text_fields.editor.setPlaceholderText(
            "Printed above the table, like: One row per visit. Use a dark pen."
        )

        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, MAX_TABLE_ROWS)
        self.rows_spin.setToolTip("How many rows are printed for people to fill in")
        self.fill_page_check = QCheckBox("&Fill to end of page")
        self.fill_page_check.setToolTip(
            "Print as many rows as fit below the table on its page"
        )
        self.column_list = QListWidget()
        self.column_list.setMinimumHeight(
            self.column_list.fontMetrics().lineSpacing() * COLUMN_ROWS_VISIBLE
        )
        self.column_list.setAccessibleDescription(
            "Columns in printed order, left to right"
        )
        for key, label_text, widget in (
            ("rows", "Ro&ws", self.rows_spin),
            ("columns", "C&olumns (required)", self.column_list),
        ):
            self.field_labels[key], self.error_labels[key] = add_field_row(
                form, label_text, widget
            )
            self.field_widgets[key] = widget
            if key == "rows":
                form.addRow("", self.fill_page_check)

        self.add_column_button = QPushButton("&Add column…")
        self.edit_column_button = QPushButton("&Edit column…")
        self.remove_column_button = QPushButton("Remo&ve column")
        self.move_left_button = QPushButton("Move &left")
        self.move_right_button = QPushButton("Move ri&ght")
        self._column_buttons = (
            self.add_column_button,
            self.edit_column_button,
            self.remove_column_button,
            self.move_left_button,
            self.move_right_button,
        )
        column_actions = QWidget()
        column_actions.setAccessibleName("Column actions")
        actions_layout = QHBoxLayout(column_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        for button in self._column_buttons:
            actions_layout.addWidget(button)
        actions_layout.addStretch()
        form.addRow("", column_actions)

        self.preview_orientation_combo = QComboBox()
        for value, name in ORIENTATION_NAMES.items():
            self.preview_orientation_combo.addItem(name.capitalize(), value)
        preview_label = QLabel("&Preview on")
        preview_label.setBuddy(self.preview_orientation_combo)
        form.addRow(preview_label, self.preview_orientation_combo)
        self.preview = TablePreview()
        form.addRow("", self.preview)
        self.preview_summary = QLabel()
        self.preview_summary.setWordWrap(True)
        form.addRow("", self.preview_summary)

        self._connect_columns()
        return [
            *self.text_fields.focus_chain(),
            self.rows_spin,
            self.fill_page_check,
            self.column_list,
            *self._column_buttons,
            self.preview_orientation_combo,
        ]

    def load_fields(self, item: TableBlock | None) -> None:
        self.text_fields.set_markdown(item.instructions if item is not None else "")
        with QSignalBlocker(self.rows_spin), QSignalBlocker(self.fill_page_check):
            self.rows_spin.setValue(
                item.rows if item is not None else DEFAULT_TABLE_ROWS
            )
            self.fill_page_check.setChecked(
                item.fill_page if item is not None else False
            )
        self._columns = list(item.columns) if item is not None else []
        self._fill_column_list(0 if self._columns else -1)
        # Start the preview on the organization's own orientation.
        organization = load_organization(self._connection)
        orientation = (
            organization.orientation if organization else PAGE_ORIENTATIONS.PORTRAIT
        )
        with QSignalBlocker(self.preview_orientation_combo):
            self.preview_orientation_combo.setCurrentIndex(
                self.preview_orientation_combo.findData(orientation)
            )

    def read_item(self, name: str, item_id: str) -> TableBlock:
        return TableBlock(
            name=name,
            instructions=self.text_fields.markdown(),
            rows=self.rows_spin.value(),
            fill_page=self.fill_page_check.isChecked(),
            columns=tuple(self._columns),
            table_block_id=item_id,
        ).normalized()

    def list_items(self) -> list[TableBlock]:
        return list_table_blocks(self._connection)

    def store_item(self, item: TableBlock) -> None:
        save_table_block(self._connection, item)

    def remove_item(self, item_id: str) -> None:
        delete_table_block(self._connection, item_id)

    def copy_item(self, item: TableBlock, name: str) -> TableBlock:
        return TableBlock(
            name=name,
            instructions=item.instructions,
            rows=item.rows,
            fill_page=item.fill_page,
            columns=item.columns,
        )

    def item_id(self, item: TableBlock) -> str:
        return item.table_block_id

    def update_state(self) -> None:
        super().update_state()
        # The count is kept but set aside while the table fills its page.
        self.rows_spin.setEnabled(not self.fill_page_check.isChecked())
        self._update_column_buttons()
        self._refresh_preview()

    # --- Columns ------------------------------------------------------------------

    def add_column(self) -> None:
        column = edit_column(self, None, {column.name for column in self._columns})
        if column is None:
            return
        self._columns.append(column)
        self._fill_column_list(len(self._columns) - 1)
        self.update_state()

    def edit_selected_column(self) -> None:
        row = self.column_list.currentRow()
        if row < 0:
            return
        others = {
            column.name for index, column in enumerate(self._columns) if index != row
        }
        column = edit_column(self, self._columns[row], others)
        if column is None:
            return
        self._columns[row] = column
        self._fill_column_list(row)
        self.update_state()

    def remove_selected_column(self) -> None:
        row = self.column_list.currentRow()
        if row < 0:
            return
        del self._columns[row]
        self._fill_column_list(min(row, len(self._columns) - 1))
        self.update_state()

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
        self.update_state()

    def _connect_columns(self) -> None:
        self.rows_spin.valueChanged.connect(self.update_state)
        self.fill_page_check.toggled.connect(self.update_state)
        self.add_column_button.clicked.connect(self.add_column)
        self.edit_column_button.clicked.connect(self.edit_selected_column)
        self.remove_column_button.clicked.connect(self.remove_selected_column)
        self.move_left_button.clicked.connect(lambda: self.move_selected_column(-1))
        self.move_right_button.clicked.connect(lambda: self.move_selected_column(1))
        self.column_list.itemActivated.connect(
            lambda _item: self.edit_selected_column()
        )
        self.column_list.currentRowChanged.connect(self._update_column_buttons)
        self.preview_orientation_combo.currentIndexChanged.connect(
            self._refresh_preview
        )
        remove_shortcut = add_shortcut(
            self.column_list,
            QKeySequence.StandardKey.Delete,
            self.remove_selected_column,
        )
        # Only from the columns list; the library list's Delete deletes the table.
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

    # --- Preview ------------------------------------------------------------------

    def _refresh_preview(self) -> None:
        organization = load_organization(self._connection)
        paper_size = organization.paper_size if organization else PAPER_SIZES.LETTER
        orientation = self.preview_orientation_combo.currentData()
        table = self.read_item(self.name_edit.text(), self._editing_id)
        self.preview.set_table(table, paper_size, orientation)
        self.preview_summary.setText(fit_summary(table, paper_size, orientation))
