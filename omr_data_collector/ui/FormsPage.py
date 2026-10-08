from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QKeySequence, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.constants import (
    BLOCK_KINDS,
    PAGE_ORIENTATIONS,
    PAPER_SIZES,
    TABLE_BREAKS,
)
from omr_data_collector.models.Form import KIND_NAMES, Form, FormBlock, content_id
from omr_data_collector.storage.form_store import (
    delete_form,
    is_printed,
    list_forms,
    save_form,
)
from omr_data_collector.storage.organization_store import load_organization
from omr_data_collector.storage.question_store import list_questions
from omr_data_collector.storage.table_block_store import list_table_blocks
from omr_data_collector.storage.text_block_store import list_text_blocks
from omr_data_collector.ui.BlockDialogs import BlockContentDialog, BlockPickerDialog
from omr_data_collector.ui.BlockPalette import BlockPalette
from omr_data_collector.ui.form_helpers import add_field_row, add_shortcut
from omr_data_collector.ui.LibraryPage import LibraryPage
from omr_data_collector.ui.OpenFormDialog import OpenFormDialog
from omr_data_collector.ui.PageCanvas import PageCanvas
from omr_data_collector.ui.TablePreview import ORIENTATION_NAMES

if TYPE_CHECKING:
    import sqlite3

    from PySide6.QtGui import QShowEvent

    from omr_data_collector.models.Form import BlockContent

TABLE_BREAK_LABELS = {
    TABLE_BREAKS.SPLIT: "Split it across pages",
    TABLE_BREAKS.NEW_PAGE: "Move it to the start of a new page",
}
BLOCK_ROWS_VISIBLE = 8
PAGES_MIN_WIDTH = 420
PALETTE_START_WIDTH = 230
DETAILS_START_WIDTH = 340
# Larger than any screen: the splitter scales the sizes down, so the pages get
# whatever the side panels don't.
PAGES_START_WIDTH = 4000
# Blocks written on the form itself can be; table copies are edited in the
# library for now.
EDITABLE_KINDS = {BLOCK_KINDS.TEXT, BLOCK_KINDS.QUESTION}


def pick_block(
    parent: QWidget, kind: str, items: list[BlockContent]
) -> tuple[bool, BlockContent | None]:
    """Ask which library block to copy.

    Returns:
        Whether the person went ahead, and the block picked (None meaning they
        chose to write a new one).
    """
    dialog = BlockPickerDialog(
        parent, KIND_NAMES[kind], items, can_write_new=kind in EDITABLE_KINDS
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False, None
    return True, dialog.chosen()


def write_block(
    parent: QWidget, kind: str, content: BlockContent | None
) -> BlockContent | None:
    """Write a new text block or question, or edit a form's copy; None if cancelled."""
    dialog = BlockContentDialog(parent, kind, content)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.content()


def choose_form(parent: QWidget, forms: list[Form], printed: set[str]) -> str | None:
    """Ask which form to open; its ID, or None if cancelled."""
    dialog = OpenFormDialog(parent, forms, printed)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.chosen_form_id()


def block_summary(number: int, block: FormBlock) -> str:
    """One line describing a block, for the blocks list and screen readers."""
    origin = "from the library" if block.source_id else "written on this form"
    parts = [
        f"{number}. {KIND_NAMES[block.kind].capitalize()}: {block.content.name}",
        origin,
    ]
    if block.start_on_new_page:
        parts.append("starts a new page")
    if block.kind == BLOCK_KINDS.TABLE:
        parts.append(
            "moves to a new page if it doesn't fit"
            if block.table_break == TABLE_BREAKS.NEW_PAGE
            else "splits across pages if it doesn't fit"
        )
    return parts[0] + " (" + ", ".join(parts[1:]) + ")"


class FormsPage(LibraryPage):
    """The form editor: the pages as they will print (wiki 50001-50012).

    The libraries' blocks are on the left, to drag onto the pages; the pages fill
    the middle, where blocks are picked and dragged up and down; the form's
    details and its Outline are on the right. The Outline and its buttons do
    everything the dragging does, for keyboard and screen-reader users. Forms are
    opened from File > Open form, like documents.

    Each block is the form's own copy: of a library block, or written here. Every
    page has a header with the organization's identity and, in the top-right
    corner, the form's QR code.
    """

    NOUN = "form"
    LIST_LABEL = "Form li&brary"
    NAME_LABEL = "Na&me (required)"
    NEW_HINT = "Enter a name, then add blocks."
    SHOW_LIBRARY = False

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__(connection)
        self.initial_focus = self.block_list
        # Tab runs left to right: the palette, then the form's details.
        for before, after in pairwise(
            [*self.block_palette.focus_chain(), self.name_edit]
        ):
            QWidget.setTabOrder(before, after)

    def wrap_editor(self, editor_box: QWidget) -> QWidget:
        self.block_palette = BlockPalette()
        self.block_palette.add_requested.connect(
            lambda kind, item_id: self.add_library_block(kind, item_id, None)
        )
        palette_box = QGroupBox("Blocks to add")
        palette_layout = QVBoxLayout(palette_box)
        palette_layout.addWidget(self.block_palette)

        self.canvas = PageCanvas()
        self.canvas.block_clicked.connect(self.block_list.setCurrentRow)
        self.canvas.block_activated.connect(self._edit_block_at)
        self.canvas.library_block_dropped.connect(self.add_library_block)
        self.canvas.block_moved.connect(self.move_block_to)
        self.page_scroll = QScrollArea()
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setWidget(self.canvas)
        self.page_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.page_scroll.setMinimumWidth(PAGES_MIN_WIDTH)
        # The desk around the paper, like a word processor's.
        self.page_scroll.setBackgroundRole(QPalette.ColorRole.Dark)

        self.splitter = QSplitter()
        self.splitter.addWidget(palette_box)
        self.splitter.addWidget(self.page_scroll)
        self.splitter.addWidget(editor_box)
        # Spare width goes to the pages.
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        # Start the side panels at a modest width and give the pages the rest;
        # the dividers can be dragged.
        self.splitter.setSizes(
            [PALETTE_START_WIDTH, PAGES_START_WIDTH, DETAILS_START_WIDTH]
        )
        return self.splitter

    def build_fields(self, form: QFormLayout) -> list[QWidget]:
        self._blocks: list[FormBlock] = []
        # Labels above their fields: the details panel beside the pages is narrow.
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.orientation_combo = QComboBox()
        for value, name in ORIENTATION_NAMES.items():
            self.orientation_combo.addItem(name.capitalize(), value)
        self.version_note = QLabel()
        self.version_note.setWordWrap(True)
        self.block_list = QListWidget()
        self.block_list.setMinimumHeight(
            self.block_list.fontMetrics().lineSpacing() * BLOCK_ROWS_VISIBLE
        )
        self.block_list.setAccessibleDescription(
            "Blocks in printed order, top of the first page down"
        )
        for key, label_text, widget in (
            ("orientation", "Page &orientation", self.orientation_combo),
            ("blocks", "B&locks (required)", self.block_list),
        ):
            self.field_labels[key], self.error_labels[key] = add_field_row(
                form, label_text, widget
            )
            self.field_widgets[key] = widget
            if key == "orientation":
                form.addRow("", self.version_note)

        self.add_text_button = QPushButton("Add te&xt…")
        self.add_question_button = QPushButton("Add quest&ion…")
        self.add_table_button = QPushButton("Add tabl&e…")
        self.edit_block_button = QPushButton("Edit blo&ck…")
        self.remove_block_button = QPushButton("Remo&ve block")
        self.move_up_button = QPushButton("Move up")
        self.move_down_button = QPushButton("Move down")
        self._block_buttons = (
            self.add_text_button,
            self.add_question_button,
            self.add_table_button,
            self.edit_block_button,
            self.remove_block_button,
            self.move_up_button,
            self.move_down_button,
        )
        # Two columns, so the buttons fit the narrow details panel.
        actions = QWidget()
        actions.setAccessibleName("Block actions")
        actions_layout = QGridLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        for number, button in enumerate(self._block_buttons):
            actions_layout.addWidget(button, number // 2, number % 2)
        form.addRow(actions)

        self.new_page_check = QCheckBox("Start on a new pa&ge")
        self.new_page_check.setToolTip(
            "Begin a new page with this block, even if it would fit"
        )
        form.addRow("", self.new_page_check)
        self.table_break_combo = QComboBox()
        for value, label in TABLE_BREAK_LABELS.items():
            self.table_break_combo.addItem(label, value)
        table_break_label = QLabel("If t&he table doesn't fit")
        table_break_label.setBuddy(self.table_break_combo)
        form.addRow(table_break_label, self.table_break_combo)

        self._connect_blocks()
        return [
            self.orientation_combo,
            self.block_list,
            *self._block_buttons,
            self.new_page_check,
            self.table_break_combo,
        ]

    def load_fields(self, item: Form | None) -> None:
        with QSignalBlocker(self.orientation_combo):
            self.orientation_combo.setCurrentIndex(
                self.orientation_combo.findData(
                    item.orientation if item is not None else PAGE_ORIENTATIONS.PORTRAIT
                )
            )
        self._blocks = list(item.blocks) if item is not None else []
        self._fill_block_list(0 if self._blocks else -1)
        self._update_version_note(item)

    def read_item(self, name: str, item_id: str) -> Form:
        return Form(
            name=name,
            orientation=self.orientation_combo.currentData(),
            blocks=tuple(self._blocks),
            form_id=item_id,
            version=self._current.version if self._current is not None else 0,
        ).normalized()

    def list_items(self) -> list[Form]:
        return list_forms(self._connection)

    def store_item(self, item: Form) -> None:
        save_form(self._connection, item)

    def remove_item(self, item_id: str) -> None:
        delete_form(self._connection, item_id)

    def copy_item(self, item: Form, name: str) -> Form:
        # New block IDs too: the copy is a separate form from the start.
        return Form(
            name=name,
            orientation=item.orientation,
            blocks=tuple(
                FormBlock(
                    content=block.content,
                    source_id=block.source_id,
                    start_on_new_page=block.start_on_new_page,
                    table_break=block.table_break,
                )
                for block in item.blocks
            ),
        )

    def item_id(self, item: Form) -> str:
        return item.form_id

    def delete_question(self, item: Form) -> str:
        if any(
            is_printed(self._connection, item.form_id, version)
            for version in range(1, item.version + 1)
        ):
            return (
                f'Delete the form "{item.name}"? It has been printed: once it is '
                "deleted, sheets printed from it can no longer be scanned. This can't "
                "be undone."
            )
        return super().delete_question(item)

    def saved_message(self, item: Form) -> str:
        return f'Form "{item.name}" saved as version {item.version}.'

    def update_state(self) -> None:
        super().update_state()
        self._update_block_controls()
        self._refresh_pages()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt override)
        # The libraries may have changed in their own sections meanwhile.
        self.refresh_palette()
        self._refresh_pages()
        super().showEvent(event)

    def open_from_list(self) -> None:
        """File > Open form: pick a saved form and open it here."""
        forms = list_forms(self._connection)
        printed = {
            form.form_id
            for form in forms
            if is_printed(self._connection, form.form_id, form.version)
        }
        form_id = choose_form(self, forms, printed)
        if form_id is not None and self.open_item(form_id):
            self.status_message.emit(f'Opened the form "{self.name_edit.text()}".')

    def refresh_palette(self) -> None:
        for kind, items in self._libraries().items():
            self.block_palette.set_items(kind, items)

    def add_library_block(self, kind: str, item_id: str, index: int | None) -> None:
        """Copy a library block onto the form at ``index`` (None: under the selection)."""
        chosen = next(
            (item for item in self._libraries()[kind] if content_id(item) == item_id),
            None,
        )
        if chosen is None:
            return
        self._insert_block(FormBlock(content=chosen, source_id=item_id), index)
        self.status_message.emit(f'Added "{chosen.name}" to the form.')

    def move_block_to(self, from_index: int, insert_index: int) -> None:
        """Move a block so it sits where ``insert_index`` points (before the move)."""
        if not 0 <= from_index < len(self._blocks):
            return
        target = insert_index - 1 if insert_index > from_index else insert_index
        target = max(0, min(target, len(self._blocks) - 1))
        if target == from_index:
            return
        block = self._blocks.pop(from_index)
        self._blocks.insert(target, block)
        self._fill_block_list(target)
        self.update_state()
        self.status_message.emit(
            f'Moved "{block.content.name}" to position {target + 1} of {len(self._blocks)}.'
        )

    # --- Blocks -------------------------------------------------------------------

    def add_block(self, kind: str) -> None:
        went_ahead, chosen = pick_block(self, kind, self._libraries()[kind])
        if not went_ahead:
            return
        if chosen is not None:
            block = FormBlock(content=chosen, source_id=content_id(chosen))
        else:
            written = write_block(self, kind, None)
            if written is None:
                return
            block = FormBlock(content=written, source_id=None)
        self._insert_block(block, None)

    def _insert_block(self, block: FormBlock, index: int | None) -> None:
        """Insert at ``index``, or when None under the selected block (or at the end)."""
        if index is None:
            row = self.block_list.currentRow()
            index = row + 1 if row >= 0 else len(self._blocks)
        index = max(0, min(index, len(self._blocks)))
        self._blocks.insert(index, block)
        self._fill_block_list(index)
        self.update_state()

    def _libraries(self) -> dict[str, list[BlockContent]]:
        return {
            BLOCK_KINDS.TEXT: list(list_text_blocks(self._connection)),
            BLOCK_KINDS.QUESTION: list(list_questions(self._connection)),
            BLOCK_KINDS.TABLE: list(list_table_blocks(self._connection)),
        }

    def _edit_block_at(self, index: int) -> None:
        self.block_list.setCurrentRow(index)
        self.edit_selected_block()

    def _refresh_pages(self) -> None:
        organization = load_organization(self._connection)
        paper_size = organization.paper_size if organization else PAPER_SIZES.LETTER
        self.canvas.set_form(
            self.read_item(self.name_edit.text(), self._editing_id),
            organization,
            paper_size,
        )
        self.canvas.select(self.block_list.currentRow())

    def edit_selected_block(self) -> None:
        row = self.block_list.currentRow()
        if row < 0 or self._blocks[row].kind not in EDITABLE_KINDS:
            return
        block = self._blocks[row]
        content = write_block(self, block.kind, block.content)
        if content is None:
            return
        self._blocks[row] = replace(block, content=content)
        self._fill_block_list(row)
        self.update_state()

    def remove_selected_block(self) -> None:
        row = self.block_list.currentRow()
        if row < 0:
            return
        del self._blocks[row]
        self._fill_block_list(min(row, len(self._blocks) - 1))
        self.update_state()

    def move_selected_block(self, offset: int) -> None:
        row = self.block_list.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < len(self._blocks):
            return
        self._blocks[row], self._blocks[target] = (
            self._blocks[target],
            self._blocks[row],
        )
        self._fill_block_list(target)
        self.update_state()

    def _connect_blocks(self) -> None:
        self.orientation_combo.currentIndexChanged.connect(self.update_state)
        self.add_text_button.clicked.connect(lambda: self.add_block(BLOCK_KINDS.TEXT))
        self.add_question_button.clicked.connect(
            lambda: self.add_block(BLOCK_KINDS.QUESTION)
        )
        self.add_table_button.clicked.connect(lambda: self.add_block(BLOCK_KINDS.TABLE))
        self.edit_block_button.clicked.connect(self.edit_selected_block)
        self.remove_block_button.clicked.connect(self.remove_selected_block)
        self.move_up_button.clicked.connect(lambda: self.move_selected_block(-1))
        self.move_down_button.clicked.connect(lambda: self.move_selected_block(1))
        self.block_list.itemActivated.connect(lambda _item: self.edit_selected_block())
        self.block_list.currentRowChanged.connect(self._update_block_controls)
        self.block_list.currentRowChanged.connect(lambda row: self.canvas.select(row))
        self.new_page_check.toggled.connect(self._set_start_on_new_page)
        self.table_break_combo.activated.connect(self._set_table_break)
        remove_shortcut = add_shortcut(
            self.block_list, QKeySequence.StandardKey.Delete, self.remove_selected_block
        )
        # Only from the blocks list; the library list's Delete deletes the form.
        remove_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.shortcuts.append(remove_shortcut)

    def _set_start_on_new_page(self, checked: bool) -> None:  # noqa: FBT001 (Qt signal)
        row = self.block_list.currentRow()
        if row < 0:
            return
        self._blocks[row] = replace(self._blocks[row], start_on_new_page=checked)
        self._fill_block_list(row)
        self.update_state()

    def _set_table_break(self, index: int) -> None:
        row = self.block_list.currentRow()
        if row < 0:
            return
        self._blocks[row] = replace(
            self._blocks[row], table_break=self.table_break_combo.itemData(index)
        )
        self._fill_block_list(row)
        self.update_state()

    def _fill_block_list(self, select_row: int) -> None:
        with QSignalBlocker(self.block_list):
            self.block_list.clear()
            for number, block in enumerate(self._blocks, start=1):
                self.block_list.addItem(block_summary(number, block))
            self.block_list.setCurrentRow(select_row)

    def _update_block_controls(self) -> None:
        row = self.block_list.currentRow()
        block = self._blocks[row] if row >= 0 else None
        self.edit_block_button.setEnabled(
            block is not None and block.kind in EDITABLE_KINDS
        )
        self.edit_block_button.setToolTip(
            "Tables are edited in the Tables section"
            if block is not None and block.kind == BLOCK_KINDS.TABLE
            else "Edit this form's copy of the block"
        )
        self.remove_block_button.setEnabled(block is not None)
        self.move_up_button.setEnabled(row > 0)
        self.move_down_button.setEnabled(
            block is not None and row < len(self._blocks) - 1
        )
        with (
            QSignalBlocker(self.new_page_check),
            QSignalBlocker(self.table_break_combo),
        ):
            self.new_page_check.setEnabled(block is not None)
            self.new_page_check.setChecked(
                block is not None and block.start_on_new_page
            )
            is_table = block is not None and block.kind == BLOCK_KINDS.TABLE
            self.form.setRowVisible(self.table_break_combo, is_table)
            if is_table and block is not None:
                self.table_break_combo.setCurrentIndex(
                    self.table_break_combo.findData(block.table_break)
                )

    def _update_version_note(self, item: Form | None) -> None:
        if item is None or item.version == 0:
            self.version_note.setText("Saving creates version 1.")
        elif is_printed(self._connection, item.form_id, item.version):
            self.version_note.setText(
                f"Version {item.version} has been printed, so it is kept as it is; "
                f"saving changes creates version {item.version + 1}."
            )
        else:
            self.version_note.setText(
                f"Version {item.version}. Changes are saved into it until it is printed."
            )
