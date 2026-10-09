from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.export.data_export import (
    JSON_FILE,
    SHEETS_FILE,
    ExportNames,
    safe_file_name,
)
from omr_data_collector.i18n import tr
from omr_data_collector.ui.accessibility import style_error_label

if TYPE_CHECKING:
    from collections.abc import Sequence

    from omr_data_collector.export.data_export import OutputFile

WHAT_COLUMN, DEFAULT_COLUMN, NAME_COLUMN = 0, 1, 2
FILE_ROW, COLUMN_ROW = "file", "column"
TABLE_ROWS_VISIBLE = 14


class ExportNamesDialog(QDialog):
    """Rename a form's exported files and columns; blank keeps the default.

    One row per file, followed by a row for each of its columns. Names are
    kept for the form, so every export uses them until changed again.
    """

    def __init__(
        self,
        parent: QWidget | None,
        files: Sequence[OutputFile],
        names: ExportNames,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Export names"))
        self._files = list(files)
        self._accepted: ExportNames | None = None

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [tr("Output"), tr("Default name"), tr("Export name")]
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
            "Each file, then its columns. Type a name in the Export name column "
            "to use it instead of the default; leave it blank to keep the default."
        )
        self.table.setAccessibleDescription(self._description)
        label = QLabel(tr("&Names"))
        label.setBuddy(self.table)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        style_error_label(self.error_label, self.palette())

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
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttons)

        self._fill(names)
        self.table.setFocus(Qt.FocusReason.OtherFocusReason)
        self.table.setCurrentCell(0, NAME_COLUMN)

    def names(self) -> ExportNames | None:
        """The accepted names; None until OK is pressed with no clashes."""
        return self._accepted

    def entered(self) -> ExportNames:
        """The names as typed: only those that differ from their defaults."""
        names = ExportNames()
        for row in range(self.table.rowCount()):
            kind, key, default = self._row_data(row)
            name = self._cell(row, NAME_COLUMN).strip()
            if not name or name == default:
                continue
            if kind == FILE_ROW:
                names.files[key] = name
            else:
                names.columns.setdefault(key, {})[default] = name
        return names

    def reset(self) -> None:
        for row in range(self.table.rowCount()):
            self.table.setItem(row, NAME_COLUMN, QTableWidgetItem(""))
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
        rows: list[tuple[str, str, str, str, str]] = []
        for output in self._files:
            if output.key == SHEETS_FILE:
                what = tr("File of sheets (CSV)")
            elif output.key == JSON_FILE:
                what = tr("JSON file")
            else:
                what = tr('File of the table "{table}" (CSV)').format(table=output.key)
            current = names.files.get(output.key, "")
            rows.append((FILE_ROW, output.key, output.default_name, what, current))
            # Each column, indented under its file's row.
            rows.extend(
                (
                    COLUMN_ROW,
                    output.key,
                    column,
                    "    " + tr("Column"),
                    names.columns.get(output.key, {}).get(column, ""),
                )
                for column in output.columns
            )
        self.table.setRowCount(len(rows))
        for row, (kind, key, default, what, current) in enumerate(rows):
            what_item = QTableWidgetItem(what)
            what_item.setData(Qt.ItemDataRole.UserRole, (kind, key, default))
            default_item = QTableWidgetItem(default)
            for item in (what_item, default_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, WHAT_COLUMN, what_item)
            self.table.setItem(row, DEFAULT_COLUMN, default_item)
            self.table.setItem(row, NAME_COLUMN, QTableWidgetItem(current))

    def _clash(self, names: ExportNames) -> str:
        """A message if two CSV files, or two columns of one file, share a name."""
        seen: dict[str, str] = {}
        for output in self._files:
            if output.key == JSON_FILE:
                continue
            name = safe_file_name(names.file_name(output.key, output.default_name))
            if name.casefold() in seen:
                return tr('Two files would both be called "{name}".').format(name=name)
            seen[name.casefold()] = output.key
        for output in self._files:
            used: set[str] = set()
            for column in output.columns:
                name = names.column(output.key, column)
                if name.casefold() in used:
                    return tr(
                        'Two columns of "{file}" would both be called "{name}".'
                    ).format(
                        file=names.file_name(output.key, output.default_name),
                        name=name,
                    )
                used.add(name.casefold())
        return ""

    def _show_error(self, message: str) -> None:
        """Show a clash, which screen readers also read with the table."""
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))
        self.table.setAccessibleDescription(message or self._description)

    def _row_data(self, row: int) -> tuple[str, str, str]:
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
