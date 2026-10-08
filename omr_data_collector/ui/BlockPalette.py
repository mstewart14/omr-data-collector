from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.constants import BLOCK_KINDS
from omr_data_collector.i18n import tr
from omr_data_collector.models.Form import content_id
from omr_data_collector.ui.PageCanvas import library_block_mime

if TYPE_CHECKING:
    from collections.abc import Sequence

    from PySide6.QtCore import QMimeData

    from omr_data_collector.models.Form import BlockContent


def _sections() -> tuple[tuple[str, str, str, str], ...]:
    """Each library: its kind, title, list name and Add button name."""
    return (
        (
            BLOCK_KINDS.TEXT,
            tr("Text blocks"),
            tr("Text blocks in the library"),
            tr("Add the selected text block to the form"),
        ),
        (
            BLOCK_KINDS.QUESTION,
            tr("Questions"),
            tr("Questions in the library"),
            tr("Add the selected question to the form"),
        ),
        (
            BLOCK_KINDS.TABLE,
            tr("Tables"),
            tr("Tables in the library"),
            tr("Add the selected table to the form"),
        ),
    )


ROWS_VISIBLE = 5


class _LibraryList(QListWidget):
    """One library's blocks, dragged out as ``LIBRARY_BLOCK_MIME``."""

    def __init__(self, kind: str) -> None:
        super().__init__()
        self.kind = kind
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def mimeData(self, items: Sequence[QListWidgetItem]) -> QMimeData:  # noqa: N802 (Qt override)
        return library_block_mime(self.kind, items[0].data(Qt.ItemDataRole.UserRole))


class BlockPalette(QWidget):
    """The libraries' blocks, to drag onto the form's pages or add with a button."""

    # A library block's kind and ID, chosen with Add to form (or Enter).
    add_requested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.lists: dict[str, _LibraryList] = {}
        self.add_buttons: dict[str, QPushButton] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        hint = QLabel(
            tr("Drag a block onto the page, or select it and press Add to form.")
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        for kind, title, list_name, add_name in _sections():
            item_list = _LibraryList(kind)
            item_list.setAccessibleName(list_name)
            item_list.setMinimumHeight(
                item_list.fontMetrics().lineSpacing() * ROWS_VISIBLE
            )
            label = QLabel(title)
            label.setBuddy(item_list)
            add_button = QPushButton(tr("Add to form"))
            add_button.setAccessibleName(add_name)
            add_button.clicked.connect(
                lambda _checked=False, kind=kind: self._add(kind)
            )
            item_list.itemActivated.connect(lambda _item, kind=kind: self._add(kind))
            item_list.currentRowChanged.connect(
                lambda row, button=add_button: button.setEnabled(row >= 0)
            )
            add_button.setEnabled(False)
            layout.addWidget(label)
            layout.addWidget(item_list, stretch=1)
            layout.addWidget(add_button)
            self.lists[kind] = item_list
            self.add_buttons[kind] = add_button

    def set_items(self, kind: str, items: Sequence[BlockContent]) -> None:
        item_list = self.lists[kind]
        item_list.clear()
        for item in items:
            list_item = QListWidgetItem(item.name)
            list_item.setData(Qt.ItemDataRole.UserRole, content_id(item))
            item_list.addItem(list_item)
        self.add_buttons[kind].setEnabled(False)

    def focus_chain(self) -> list[QWidget]:
        chain: list[QWidget] = []
        for kind in self.lists:
            chain += [self.lists[kind], self.add_buttons[kind]]
        return chain

    def _add(self, kind: str) -> None:
        item = self.lists[kind].currentItem()
        if item is not None:
            self.add_requested.emit(kind, item.data(Qt.ItemDataRole.UserRole))
