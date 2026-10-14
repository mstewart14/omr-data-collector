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
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.export.data_export import SHEETS_FILE, ExportNames
from omr_data_collector.i18n import tr
from omr_data_collector.ui.accessibility import style_error_label

if TYPE_CHECKING:
    from collections.abc import Sequence

    from omr_data_collector.export.data_export import OutputFile

WHAT_COLUMN, DEFAULT_COLUMN, NAME_COLUMN = 0, 1, 2
TABLE_ROWS_VISIBLE = 14


def file_label(key: str) -> str:
    """Which file a column is in: the sheets file, or a table's."""
    if key == SHEETS_FILE:
        return tr("Sheets")
    return tr('Table "{table}"').format(table=key)


class ExportNamesDialog(QDialog):
    """Choose and rename a form's exported columns; blank keeps the default.

    A row for each column, the sheets file's first, then each table's, ticked
    to export it (all are, to start with), in the order they're exported: Move
    up and Move down reorder a file's columns. Kept for the form, so every export
    (CSV or JSON) uses them until changed again. Files are named when exporting.
    """

    def __init__(
        self,
        parent: QWidget | None,
        files: Sequence[OutputFile],
        names: ExportNames,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Columns"))
        self._files = list(files)
        self._accepted: ExportNames | None = None

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [tr("File"), tr("Column"), tr("Export name")]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setTabKeyNavigation(False)
        self.table.setMinimumHeight(
            self.table.verticalHeader().defaultSectionSize() * TABLE_ROWS_VISIBLE
        )
        self._description = tr(
            "Each column, the sheets file's first, then each table's, in the "
            "order they're exported: use Move up and Move down to change it. "
            "Untick a column to leave it out of the export (in JSON, only answers "
            "and sheet details are left out or reordered). Type a name in the "
            "Export name column to use it instead; leave it blank to keep the "
            "column's own name."
        )
        self.table.setAccessibleDescription(self._description)
        label = QLabel(tr("&Columns to export"))
        label.setBuddy(self.table)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        style_error_label(self.error_label, self.palette())

        self.move_up_button = QPushButton(tr("Move up"))
        self.move_down_button = QPushButton(tr("Move down"))
        self.move_up_button.clicked.connect(lambda: self.move_column(-1))
        self.move_down_button.clicked.connect(lambda: self.move_column(1))
        moves = QWidget()
        moves.setAccessibleName(tr("Column order"))
        moves_layout = QHBoxLayout(moves)
        moves_layout.setContentsMargins(0, 0, 0, 0)
        moves_layout.addWidget(self.move_up_button)
        moves_layout.addWidget(self.move_down_button)
        moves_layout.addStretch()
        self.table.currentCellChanged.connect(self._update_moves)

        self.reset_button = QPushButton(tr("&Reset to defaults"))
        self.reset_button.clicked.connect(self.reset)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.addButton(self.reset_button, QDialogButtonBox.ButtonRole.ResetRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.table)
        layout.addWidget(moves)
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttons)

        self._fill(names)
        self.table.setFocus(Qt.FocusReason.OtherFocusReason)
        self.table.setCurrentCell(0, NAME_COLUMN)
        self._update_moves()

    def names(self) -> ExportNames | None:
        """The accepted names; None until OK is pressed with no clashes."""
        return self._accepted

    def entered(self) -> ExportNames:
        """The names as typed: only those that differ from their defaults."""
        names = ExportNames()
        order: dict[str, list[str]] = {}
        for row in range(self.table.rowCount()):
            key, default = self._row_data(row)
            order.setdefault(key, []).append(default)
            name = self._cell(row, NAME_COLUMN).strip()
            if name and name != default:
                names.columns.setdefault(key, {})[default] = name
            if not self.is_ticked(row):
                names.left_out.setdefault(key, []).append(default)
        for output in self._files:
            if order.get(output.key, []) != list(output.columns):
                names.order[output.key] = order[output.key]
        return names

    def move_column(self, offset: int) -> None:
        """Move the current column up or down among its own file's columns."""
        row = self.table.currentRow()
        target = row + offset
        if not self._can_move(row, target):
            return
        column = self.table.currentColumn()
        for cell in range(self.table.columnCount()):
            here = self.table.takeItem(row, cell)
            there = self.table.takeItem(target, cell)
            self.table.setItem(row, cell, there)
            self.table.setItem(target, cell, here)
        self.table.setCurrentCell(target, column)
        self._update_moves()

    def _can_move(self, row: int, target: int) -> bool:
        if row < 0 or not 0 <= target < self.table.rowCount():
            return False
        return self._row_data(row)[0] == self._row_data(target)[0]

    def _update_moves(self) -> None:
        row = self.table.currentRow()
        self.move_up_button.setEnabled(self._can_move(row, row - 1))
        self.move_down_button.setEnabled(self._can_move(row, row + 1))

    def is_ticked(self, row: int) -> bool:
        item = self.table.item(row, DEFAULT_COLUMN)
        return item is not None and item.checkState() == Qt.CheckState.Checked

    def reset(self) -> None:
        """Every column exported, in its own order, under its own name."""
        self._fill(ExportNames())
        self._update_moves()
        self._show_error("")

    def accept(self) -> None:
        names = self.entered()
        problem = self._clash(names)
        self._show_error(problem)
        if problem:
            self.table.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        self._accepted = names
        super().accept()

    def _fill(self, names: ExportNames) -> None:
        rows = [
            (output.key, column, names.columns.get(output.key, {}).get(column, ""))
            for output in self._files
            for column in names.ordered(output.key, list(output.columns))
        ]
        self.table.setRowCount(len(rows))
        for row, (key, default, current) in enumerate(rows):
            what_item = QTableWidgetItem(file_label(key))
            what_item.setData(Qt.ItemDataRole.UserRole, (key, default))
            default_item = QTableWidgetItem(default)
            for item in (what_item, default_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            default_item.setFlags(
                default_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            )
            default_item.setCheckState(
                Qt.CheckState.Checked
                if names.included(key, default)
                else Qt.CheckState.Unchecked
            )
            self.table.setItem(row, WHAT_COLUMN, what_item)
            self.table.setItem(row, DEFAULT_COLUMN, default_item)
            self.table.setItem(row, NAME_COLUMN, QTableWidgetItem(current))

    def _clash(self, names: ExportNames) -> str:
        """A message if a file has no columns, or two of its columns one name."""
        for output in self._files:
            exported = [
                column
                for column in output.columns
                if names.included(output.key, column)
            ]
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
                        'Two columns of the table "{table}" would both be called '
                        '"{name}".'
                    ).format(table=output.key, name=name)
        return ""

    def _show_error(self, message: str) -> None:
        """Show a clash, which screen readers also read with the table."""
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))
        self.table.setAccessibleDescription(message or self._description)

    def _row_data(self, row: int) -> tuple[str, str]:
        item = self.table.item(row, WHAT_COLUMN)
        assert item is not None  # noqa: S101 (every row is filled)
        return item.data(Qt.ItemDataRole.UserRole)

    def _cell(self, row: int, column: int) -> str:
        item = self.table.item(row, column)
        return item.text() if item is not None else ""

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.PaletteChange:
            style_error_label(self.error_label, self.palette())
        super().changeEvent(event)
