from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.export.data_export import SHEETS_FILE, ExportNames
from omr_data_collector.i18n import tr
from omr_data_collector.ui.accessibility import style_error_label
from omr_data_collector.ui.form_helpers import move_buttons, ok_cancel_buttons

if TYPE_CHECKING:
    from collections.abc import Sequence

    from omr_data_collector.export.data_export import OutputFile

DEFAULT_COLUMN, NAME_COLUMN = 0, 1
TABLE_ROWS_VISIBLE = 14


def file_label(key: str) -> str:
    """Which file it is: the sheets file, or a table's."""
    if key == SHEETS_FILE:
        return tr("Sheets file")
    return tr('Table "{table}" file').format(table=key)


def file_description(key: str) -> str:
    """What one row of a file is, and where its columns come from."""
    if key == SHEETS_FILE:
        return tr(
            "One row for each sheet: its ID, version and when it was captured, "
            "its sheet details, and its answers that aren't in a table."
        )
    return tr(
        'One row for each filled-in row of the table "{table}". Each row starts '
        "with its sheet's ID, version and sheet details, so this file can be read "
        "on its own; sheet_id matches it to the sheets file."
    ).format(table=key)


class ExportNamesDialog(QDialog):
    """Choose a form's CSV files, and choose, order and rename their columns.

    The files are listed on the left, ticked to export them (all are, to start
    with); the chosen file's columns are on the right, in the order they're
    exported, ticked to export them: Move up and Move down reorder them. A blank
    name keeps the default. Kept for the form, so every export uses them until
    changed again (JSON has every file, but leaves out and reorders the same
    columns). Files are named when exporting.
    """

    def __init__(
        self,
        parent: QWidget | None,
        files: Sequence[OutputFile],
        names: ExportNames,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Files and columns"))
        self._files = list(files)
        self._accepted: ExportNames | None = None

        self.files_list = QListWidget()
        self.files_list.setAccessibleDescription(
            tr(
                "Each file a CSV export writes. Untick a file to leave it out; "
                "choose one to see and change its columns."
            )
        )
        files_label = QLabel(tr("&Files to export"))
        files_label.setBuddy(self.files_list)
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.columns_label = QLabel()
        self.stack = QStackedWidget()
        self.tables: dict[str, QTableWidget] = {}
        self._description = tr(
            "The file's columns, in the order they're exported: use Move up and "
            "Move down to change it. Untick a column to leave it out. Type a name "
            "in the Export name column to use it instead; leave it blank to keep "
            "the column's own name."
        )
        for output in self._files:
            self.files_list.addItem(QListWidgetItem(file_label(output.key)))
            table = self._build_table()
            self.tables[output.key] = table
            self.stack.addWidget(table)
        self.files_list.currentRowChanged.connect(self._show_row)
        self.files_list.itemChanged.connect(
            lambda _item: self._describe(self.files_list.currentRow())
        )

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        style_error_label(self.error_label, self.palette())

        moves = self._build_moves()
        self._build_buttons()

        left = QVBoxLayout()
        left.addWidget(files_label)
        left.addWidget(self.files_list)
        right = QVBoxLayout()
        right.addWidget(self.description_label)
        right.addWidget(self.columns_label)
        right.addWidget(self.stack, 1)
        right.addWidget(moves)
        panes = QHBoxLayout()
        panes.addLayout(left, 1)
        panes.addLayout(right, 3)
        layout = QVBoxLayout(self)
        layout.addLayout(panes)
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttons)

        self._fill(names)
        self.files_list.setCurrentRow(0)
        self.files_list.setFocus(Qt.FocusReason.OtherFocusReason)

    def _build_moves(self) -> QWidget:
        moves, self.move_up_button, self.move_down_button = move_buttons(
            tr("Column order")
        )
        self.move_up_button.clicked.connect(lambda: self.move_column(-1))
        self.move_down_button.clicked.connect(lambda: self.move_column(1))
        return moves

    def _build_buttons(self) -> None:
        self.reset_button = QPushButton(tr("&Reset to defaults"))
        self.reset_button.clicked.connect(self.reset)
        self.buttons = ok_cancel_buttons(self)
        self.buttons.addButton(self.reset_button, QDialogButtonBox.ButtonRole.ResetRole)

    def _build_table(self) -> QTableWidget:
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels([tr("Column"), tr("Export name")])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        table.setTabKeyNavigation(False)
        table.setMinimumHeight(
            table.verticalHeader().defaultSectionSize() * TABLE_ROWS_VISIBLE
        )
        table.setAccessibleDescription(self._description)
        table.currentCellChanged.connect(self._update_moves)
        return table

    @property
    def table(self) -> QTableWidget:
        """The chosen file's columns."""
        return self.tables[self.current_key()]

    def current_key(self) -> str:
        return self._files[max(self.files_list.currentRow(), 0)].key

    def show_file(self, key: str) -> None:
        """Show ``key``'s file's columns."""
        keys = [output.key for output in self._files]
        self.files_list.setCurrentRow(keys.index(key))

    def _show_row(self, row: int) -> None:
        if row < 0:
            return
        key = self._files[row].key
        self.stack.setCurrentIndex(row)
        self._describe(row)
        if key == SHEETS_FILE:
            self.columns_label.setText(tr("&Columns of the sheets file"))
        else:
            self.columns_label.setText(
                tr('&Columns of the table "{table}" file').format(table=key)
            )
        self.columns_label.setBuddy(self.table)
        if self.table.currentRow() < 0 and self.table.rowCount():
            self.table.setCurrentCell(0, NAME_COLUMN)
        self._update_moves()

    def _describe(self, row: int) -> None:
        if row < 0:
            return
        description = file_description(self._files[row].key)
        if not self.file_is_ticked(row):
            description += " " + tr(
                "This file isn't exported: tick it on the left to export it."
            )
        self.description_label.setText(description)

    def names(self) -> ExportNames | None:
        """The accepted names; None until OK is pressed with no clashes."""
        return self._accepted

    def entered(self) -> ExportNames:
        """The choices as made: only those that differ from their defaults."""
        names = ExportNames()
        for index, output in enumerate(self._files):
            table = self.tables[output.key]
            order: list[str] = []
            for row in range(table.rowCount()):
                default = self._default(table, row)
                order.append(default)
                name = self._cell(table, row, NAME_COLUMN).strip()
                if name and name != default:
                    names.columns.setdefault(output.key, {})[default] = name
                if not self.is_ticked(row, table):
                    names.left_out.setdefault(output.key, []).append(default)
            if order != list(output.columns):
                names.order[output.key] = order
            if not self.file_is_ticked(index):
                names.skipped.append(output.key)
        return names

    def move_column(self, offset: int) -> None:
        """Move the current column up or down among its file's columns."""
        table = self.table
        row = table.currentRow()
        target = row + offset
        if not self._can_move(row, target):
            return
        column = table.currentColumn()
        for cell in range(table.columnCount()):
            here = table.takeItem(row, cell)
            there = table.takeItem(target, cell)
            table.setItem(row, cell, there)
            table.setItem(target, cell, here)
        table.setCurrentCell(target, column)
        self._update_moves()

    def _can_move(self, row: int, target: int) -> bool:
        return row >= 0 and 0 <= target < self.table.rowCount()

    def _update_moves(self) -> None:
        row = self.table.currentRow()
        self.move_up_button.setEnabled(self._can_move(row, row - 1))
        self.move_down_button.setEnabled(self._can_move(row, row + 1))

    def is_ticked(self, row: int, table: QTableWidget | None = None) -> bool:
        item = (table or self.table).item(row, DEFAULT_COLUMN)
        return item is not None and item.checkState() == Qt.CheckState.Checked

    def file_is_ticked(self, index: int) -> bool:
        item = self.files_list.item(index)
        return item is not None and item.checkState() == Qt.CheckState.Checked

    def reset(self) -> None:
        """Every file and column exported, in its own order, under its own name."""
        self._fill(ExportNames())
        self._update_moves()
        self._show_error("")

    def accept(self) -> None:
        names = self.entered()
        problem, key = self._clash(names)
        self._show_error(problem)
        if problem:
            if key is None:
                self.files_list.setFocus(Qt.FocusReason.OtherFocusReason)
            else:
                self.show_file(key)
                self.table.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        self._accepted = names
        super().accept()

    def _fill(self, names: ExportNames) -> None:
        for index, output in enumerate(self._files):
            item = self.files_list.item(index)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if names.exports_file(output.key)
                else Qt.CheckState.Unchecked
            )
            item.setToolTip(file_description(output.key))
            self._fill_table(self.tables[output.key], output.key, names, output)

    @staticmethod
    def _fill_table(
        table: QTableWidget, key: str, names: ExportNames, output: OutputFile
    ) -> None:
        columns = names.ordered(key, list(output.columns))
        table.setRowCount(len(columns))
        for row, default in enumerate(columns):
            default_item = QTableWidgetItem(default)
            default_item.setData(Qt.ItemDataRole.UserRole, default)
            default_item.setFlags(
                (default_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            default_item.setCheckState(
                Qt.CheckState.Checked
                if names.included(key, default)
                else Qt.CheckState.Unchecked
            )
            table.setItem(row, DEFAULT_COLUMN, default_item)
            table.setItem(
                row,
                NAME_COLUMN,
                QTableWidgetItem(names.columns.get(key, {}).get(default, "")),
            )

    def _clash(self, names: ExportNames) -> tuple[str, str | None]:
        """A message if a file to export has no columns, or two of them one name.

        With it, the key of the file to show, or None for the files list.
        """
        exported_files = [
            output for output in self._files if names.exports_file(output.key)
        ]
        if not exported_files:
            return tr("Tick at least one file to export."), None
        for output in exported_files:
            problem = self._file_clash(names, output)
            if problem:
                return problem, output.key
        return "", None

    @staticmethod
    def _file_clash(names: ExportNames, output: OutputFile) -> str:
        exported = names.exported(output.key, list(output.columns))
        if not exported and output.key == SHEETS_FILE:
            return tr("Tick at least one column of the sheets file.")
        if not exported:
            return tr('Tick at least one column of the table "{table}".').format(
                table=output.key
            )
        used: set[str] = set()
        for column in exported:
            name = names.column(output.key, column)
            if name.casefold() not in used:
                used.add(name.casefold())
            elif output.key == SHEETS_FILE:
                return tr(
                    'Two columns of the sheets file would both be called "{name}".'
                ).format(name=name)
            else:
                return tr(
                    'Two columns of the table "{table}" would both be called "{name}".'
                ).format(table=output.key, name=name)
        return ""

    def _show_error(self, message: str) -> None:
        """Show a clash, which screen readers also read with the table."""
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))
        for table in self.tables.values():
            table.setAccessibleDescription(message or self._description)

    def _row_data(self, row: int) -> tuple[str, str]:
        """The chosen file's key, and the default name of its column ``row``."""
        return self.current_key(), self._default(self.table, row)

    @staticmethod
    def _default(table: QTableWidget, row: int) -> str:
        item = table.item(row, DEFAULT_COLUMN)
        # Every row is filled in, so an item is always there.
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else ""

    @staticmethod
    def _cell(table: QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column)
        return item.text() if item is not None else ""

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.PaletteChange:
            style_error_label(self.error_label, self.palette())
        super().changeEvent(event)
