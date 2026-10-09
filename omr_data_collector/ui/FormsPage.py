from __future__ import annotations

import re
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QItemSelectionModel, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QKeySequence, QPalette
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QMessageBox,
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
from omr_data_collector.i18n import tr
from omr_data_collector.layout.form_layout import layout_form
from omr_data_collector.layout.omr_template import printed_layout
from omr_data_collector.layout.page_setup import page_layout_for
from omr_data_collector.models.Form import Form, FormBlock, content_id, kind_title
from omr_data_collector.models.ordering import move_by, move_to
from omr_data_collector.rendering.print_form import render_form, save_pdf
from omr_data_collector.storage.form_store import (
    delete_form,
    is_printed,
    list_forms,
    mark_printed,
    save_form,
)
from omr_data_collector.storage.organization_store import load_organization
from omr_data_collector.storage.question_store import list_questions
from omr_data_collector.storage.table_block_store import list_table_blocks
from omr_data_collector.storage.text_block_store import list_text_blocks
from omr_data_collector.ui.accessibility import style_error_label
from omr_data_collector.ui.BlockDialogs import BlockContentDialog, BlockPickerDialog
from omr_data_collector.ui.BlockPalette import BlockPalette
from omr_data_collector.ui.form_helpers import (
    add_field_row,
    add_shortcut,
    add_standard_shortcuts,
    ask_save_first,
    confirm_despite_problems,
    tell,
)
from omr_data_collector.ui.LibraryPage import LibraryPage, LibraryTexts
from omr_data_collector.ui.OpenFormDialog import OpenFormDialog
from omr_data_collector.ui.PageCanvas import PageCanvas
from omr_data_collector.ui.TablePreview import orientation_names

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Sequence

    from PySide6.QtGui import QShowEvent

    from omr_data_collector.models.Form import BlockContent
    from omr_data_collector.models.Organization import Organization


def table_break_labels() -> dict[str, str]:
    return {
        TABLE_BREAKS.SPLIT: tr("Split it across pages"),
        TABLE_BREAKS.NEW_PAGE: tr("Move it to the start of a new page"),
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
        parent, kind, items, can_write_new=kind in EDITABLE_KINDS
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


def choose_pdf_path(parent: QWidget, default_name: str) -> Path | None:
    """Ask where to save the PDF; None if cancelled."""
    file_name, _ = QFileDialog.getSaveFileName(
        parent, tr("Export as PDF"), default_name, tr("PDF document (*.pdf)")
    )
    if not file_name:
        return None
    path = Path(file_name)
    return path if path.suffix.lower() == ".pdf" else path.with_suffix(".pdf")


def run_print_dialog(parent: QWidget, printer: QPrinter) -> bool:
    """Show the system print dialog; True if the person chose to print."""
    return QPrintDialog(printer, parent).exec() == QDialog.DialogCode.Accepted


def run_print_preview(
    parent: QWidget, printer: QPrinter, render: Callable[[QPrinter], object]
) -> bool:
    """Show the pages as they will print; True if printed from the preview."""
    dialog = QPrintPreviewDialog(printer, parent)
    dialog.setWindowTitle(tr("Print preview"))
    dialog.paintRequested.connect(render)
    return dialog.exec() == QDialog.DialogCode.Accepted


def block_summary(number: int, block: FormBlock) -> str:
    """One line describing a block, for the blocks list and screen readers."""
    origin = tr("from the library") if block.source_id else tr("written on this form")
    parts = [origin]
    if block.start_on_new_page:
        parts.append(tr("starts a new page"))
    if block.kind == BLOCK_KINDS.TABLE:
        parts.append(
            tr("moves to a new page if it doesn't fit")
            if block.table_break == TABLE_BREAKS.NEW_PAGE
            else tr("splits across pages if it doesn't fit")
        )
    return tr("{number}. {kind}: {name} ({details})").format(
        number=number,
        kind=kind_title(block.kind),
        name=block.content.name,
        details=", ".join(parts),
    )


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

    # Printing needs the organization's details; the window opens them.
    organization_needed = Signal()

    def texts(self) -> LibraryTexts:
        return LibraryTexts(
            list_label=tr("Form li&brary"),
            name_label=tr("Na&me (required)"),
            new_title=tr("New form"),
            new_status=tr("New form. Enter a name, then add blocks."),
            new_tooltip=tr("Start a new form (Ctrl+N)"),
            duplicate_tooltip=tr("Save a copy of the selected form"),
            delete_tooltip=tr("Delete the selected form (Delete key)"),
            save_tooltip=tr("Save the form (Ctrl+S)"),
            delete_title=tr("Delete form"),
            delete_question=tr('Delete the form "{name}"? This can\'t be undone.'),
            saved=tr('Form "{name}" saved.'),
            deleted=tr('Form "{name}" deleted.'),
            name_taken=tr('Another form is already called "{name}".'),
            save_first=tr("Save your changes to this form first?"),
        )

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
        palette_box = QGroupBox(tr("Blocks to add"))
        palette_layout = QVBoxLayout(palette_box)
        palette_layout.addWidget(self.block_palette)

        self.canvas = PageCanvas()
        self.canvas.selection_requested.connect(self._on_canvas_selection)
        self.canvas.block_activated.connect(self._edit_block_at)
        self.canvas.library_block_dropped.connect(self.add_library_block)
        self.canvas.blocks_moved.connect(self.move_blocks_to)
        self.canvas.delete_requested.connect(self.remove_selected_blocks)
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
        for value, name in orientation_names().items():
            self.orientation_combo.addItem(name, value)
        self.version_note = QLabel()
        self.version_note.setWordWrap(True)
        # Layout problems to fix before printing, e.g. a table too wide.
        self.problems_note = QLabel()
        self.problems_note.setWordWrap(True)
        self.block_list = QListWidget()
        self.block_list.setMinimumHeight(
            self.block_list.fontMetrics().lineSpacing() * BLOCK_ROWS_VISIBLE
        )
        self.block_list.setAccessibleDescription(
            tr(
                "Blocks in printed order, top of the first page down. Ctrl or Shift "
                "with a click or arrow key selects several."
            )
        )
        self.block_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        for key, label_text, widget in (
            ("orientation", tr("Page &orientation"), self.orientation_combo),
            ("blocks", tr("B&locks (required)"), self.block_list),
        ):
            self.field_labels[key], self.error_labels[key] = add_field_row(
                form, label_text, widget
            )
            self.field_widgets[key] = widget
            if key == "orientation":
                form.addRow("", self.version_note)
                form.addRow("", self.problems_note)

        self.add_text_button = QPushButton(tr("Add te&xt…"))
        self.add_question_button = QPushButton(tr("Add quest&ion…"))
        self.add_table_button = QPushButton(tr("Add tabl&e…"))
        self.edit_block_button = QPushButton(tr("Edit bloc&k…"))
        self.remove_block_button = QPushButton(tr("Remo&ve block"))
        self.move_up_button = QPushButton(tr("Move up"))
        self.move_down_button = QPushButton(tr("Move down"))
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
        actions.setAccessibleName(tr("Block actions"))
        actions_layout = QGridLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        for number, button in enumerate(self._block_buttons):
            actions_layout.addWidget(button, number // 2, number % 2)
        form.addRow(actions)

        self.new_page_check = QCheckBox(tr("Start on a new pa&ge"))
        self.new_page_check.setToolTip(
            tr("Begin a new page with this block, even if it would fit")
        )
        form.addRow("", self.new_page_check)
        self.table_break_combo = QComboBox()
        for value, label in table_break_labels().items():
            self.table_break_combo.addItem(label, value)
        table_break_label = QLabel(tr("If t&he table doesn't fit"))
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
        self._fill_block_list([0] if self._blocks else [])
        self._update_version_note(item)
        # Undo goes back as far as when this form was opened.
        self._reset_history()

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
            return tr(
                'Delete the form "{name}"? It has been printed: once it is deleted, '
                "sheets printed from it can no longer be scanned. This can't be "
                "undone."
            ).format(name=item.name)
        return super().delete_question(item)

    def saved_message(self, item: Form) -> str:
        return tr('Form "{name}" saved as version {version}.').format(
            name=item.name, version=item.version
        )

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
            self.status_message.emit(
                tr('Opened the form "{name}".').format(name=self.name_edit.text())
            )

    def refresh_palette(self) -> None:
        for kind, items in self._libraries().items():
            self.block_palette.set_items(kind, items)

    def _libraries(self) -> dict[str, list[BlockContent]]:
        return {
            BLOCK_KINDS.TEXT: list(list_text_blocks(self._connection)),
            BLOCK_KINDS.QUESTION: list(list_questions(self._connection)),
            BLOCK_KINDS.TABLE: list(list_table_blocks(self._connection)),
        }

    def _edit_block_at(self, index: int) -> None:
        self.set_selection([index], index)
        self.edit_selected_block()

    def _refresh_pages(self) -> None:
        organization = load_organization(self._connection)
        paper_size = organization.paper_size if organization else PAPER_SIZES.LETTER
        self.canvas.set_form(
            self.read_item(self.name_edit.text(), self._editing_id),
            organization,
            paper_size,
        )
        self.canvas.select(self.selected_rows())
        warnings = self.canvas.form_layout.warnings if self.canvas.form_layout else ()
        self.problems_note.setText(
            tr("Check before printing: {problems}").format(problems=" ".join(warnings))
            if warnings
            else ""
        )
        style_error_label(self.problems_note, self.palette())
        self.form.setRowVisible(self.problems_note, bool(warnings))

    def add_library_block(self, kind: str, item_id: str, index: int | None) -> None:
        """Copy a library block onto the form at ``index`` (None: under the selection)."""
        chosen = next(
            (item for item in self._libraries()[kind] if content_id(item) == item_id),
            None,
        )
        if chosen is None:
            return
        self._insert_block(FormBlock(content=chosen, source_id=item_id), index)
        self._commit_change(tr('added "{name}"').format(name=chosen.name))
        self.status_message.emit(
            tr('Added "{name}" to the form.').format(name=chosen.name)
        )

    def move_blocks_to(self, indices: list[int], insert_index: int) -> None:
        """Move the blocks at ``indices``, in order, to before ``insert_index``.

        ``insert_index`` counts positions before the move, as a drop point does.
        """
        blocks, moved = move_to(self._blocks, indices, insert_index)
        if blocks == self._blocks:
            return
        self._blocks = blocks
        self._fill_block_list(moved)
        self.update_state()
        self._commit_change(_moved_description(moved))
        self.status_message.emit(_moved_status(moved, len(self._blocks)))

    # --- Selection ----------------------------------------------------------------

    def selected_rows(self) -> list[int]:
        """The selected blocks' positions, top to bottom."""
        rows = sorted(
            index.row() for index in self.block_list.selectionModel().selectedRows()
        )
        if not rows and self.block_list.currentRow() >= 0:
            return [self.block_list.currentRow()]
        return rows

    def set_selection(self, rows: Sequence[int], current: int | None = None) -> None:
        """Select ``rows`` in the Outline (and so on the pages)."""
        valid = [row for row in rows if 0 <= row < len(self._blocks)]
        model = self.block_list.selectionModel()
        with QSignalBlocker(self.block_list), QSignalBlocker(model):
            self.block_list.clearSelection()
            if current is None:
                current = valid[-1] if valid else -1
            self.block_list.setCurrentRow(
                current, QItemSelectionModel.SelectionFlag.NoUpdate
            )
            for row in valid:
                model.select(
                    self.block_list.model().index(row, 0),
                    QItemSelectionModel.SelectionFlag.Select,
                )
        self._selection_changed()

    def _on_canvas_selection(self, index: int, toggle: bool, extend: bool) -> None:  # noqa: FBT001 (Qt signal)
        rows = self.selected_rows()
        if index < 0:
            if not toggle and not extend:
                self.set_selection([])
            return
        if toggle:
            chosen = set(rows) ^ {index}
            self.set_selection(sorted(chosen), index if index in chosen else None)
        elif extend and self.block_list.currentRow() >= 0:
            anchor = self.block_list.currentRow()
            low, high = sorted((anchor, index))
            self.set_selection(list(range(low, high + 1)), anchor)
        else:
            self.set_selection([index], index)

    def _selection_changed(self) -> None:
        rows = self.selected_rows()
        self.canvas.select(rows)
        self._update_block_controls()
        # Undo puts the selection back as it was just before a change, so keep
        # the remembered state's selection current while nothing else changes.
        shown = getattr(self, "_shown", None)
        if shown is not None and shown.blocks == tuple(self._blocks):
            self._shown = replace(shown, selected=tuple(rows))

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
        self._commit_change(tr('added "{name}"').format(name=block.content.name))

    def _insert_block(self, block: FormBlock, index: int | None) -> None:
        """Insert at ``index``, or when None under the selected blocks (or at the end)."""
        if index is None:
            rows = self.selected_rows()
            index = rows[-1] + 1 if rows else len(self._blocks)
        index = max(0, min(index, len(self._blocks)))
        self._blocks.insert(index, block)
        self._fill_block_list([index])
        self.update_state()

    def edit_selected_block(self) -> None:
        row = self.block_list.currentRow()
        if row < 0 or self._blocks[row].kind not in EDITABLE_KINDS:
            return
        block = self._blocks[row]
        content = write_block(self, block.kind, block.content)
        if content is None:
            return
        self._blocks[row] = replace(block, content=content)
        self._fill_block_list([row])
        self.update_state()
        self._commit_change(tr('edited "{name}"').format(name=content.name))

    def remove_selected_blocks(self) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        removed = [self._blocks[row].content.name for row in rows]
        self._blocks = [
            block for index, block in enumerate(self._blocks) if index not in set(rows)
        ]
        self._fill_block_list(
            [min(rows[0], len(self._blocks) - 1)] if self._blocks else []
        )
        self.update_state()
        if len(removed) == 1:
            self._commit_change(tr('removed "{name}"').format(name=removed[0]))
            status = tr('Removed "{name}". Ctrl+Z undoes it.').format(name=removed[0])
        else:
            self._commit_change(tr("removed %n block(s)", None, len(removed)))
            status = tr("Removed %n block(s). Ctrl+Z undoes it.", None, len(removed))
        self.status_message.emit(status)

    def move_selected_blocks(self, offset: int) -> None:
        blocks, moved = move_by(self._blocks, self.selected_rows(), offset)
        if blocks == self._blocks:
            return
        self._blocks = blocks
        self._fill_block_list(moved)
        self.update_state()
        self._commit_change(_moved_description(moved))
        self.status_message.emit(_moved_status(moved, len(self._blocks)))

    # --- Printing (wiki 50007-50009) -----------------------------------------------

    def export_pdf(self) -> None:
        """File > Export as PDF: save the form's pages as a PDF file."""
        ready = self._ready_to_print(
            tr("The form has unsaved changes. Save it to save it as a PDF?"),
            tr("Check before you save it as a PDF:"),
        )
        if ready is None:
            return
        form, organization = ready
        path = choose_pdf_path(
            self,
            tr("{name} v{version}.pdf", "PDF file name").format(
                name=_file_name(form.name), version=form.version
            ),
        )
        if path is None:
            return
        try:
            pages = save_pdf(path, form, organization, organization.paper_size)
        except OSError as error:
            QMessageBox.warning(self, tr("Couldn't save the PDF"), str(error))
            return
        self._after_printing(
            form,
            organization,
            tr("Saved %n page(s) to {path}", None, pages).format(path=path),
        )

    def print_form(self) -> None:
        """File > Print: send the form's pages to a printer."""
        ready = self._ready_to_print(
            tr("The form has unsaved changes. Save it to print it?"),
            tr("Check before you print it:"),
        )
        if ready is None:
            return
        form, organization = ready
        printer = _printer(form, organization)
        if not run_print_dialog(self, printer):
            return
        render_form(printer, form, organization, organization.paper_size)
        self._after_printing(form, organization, tr("Sent the form to the printer"))

    def print_preview(self) -> None:
        """File > Print preview: see the pages as they will print, and print them."""
        ready = self._ready_to_print(
            tr("The form has unsaved changes. Save it to preview it?"),
            tr("Check before you preview it:"),
        )
        if ready is None:
            return
        form, organization = ready
        printer = _printer(form, organization)
        printed = run_print_preview(
            self,
            printer,
            lambda device: render_form(
                device, form, organization, organization.paper_size
            ),
        )
        if printed:
            self._after_printing(form, organization, tr("Sent the form to the printer"))

    def _ready_to_print(
        self, save_question: str, check_heading: str
    ) -> tuple[Form, Organization] | None:
        """The saved form and the organization, once both are ready to print.

        ``save_question`` asks to save unsaved changes first, and
        ``check_heading`` introduces the layout problems to confirm.

        Prints carry the organization in their header and a QR code naming a
        stored version, so the form must be saved and the organization entered.
        Layout problems (a table too wide, say) are shown before going ahead.
        """
        organization = load_organization(self._connection)
        if organization is None:
            tell(
                self,
                tr("Organization details needed"),
                tr(
                    "Enter your organization's details first, in Preferences > "
                    "Organization details: every page's header and QR code show them."
                ),
            )
            self.organization_needed.emit()
            return None
        if self._current is None or self.has_unsaved_changes():
            if not ask_save_first(self, save_question):
                return None
            if not self.save():
                return None
        form = self._current
        if form is None:
            return None
        warnings = layout_form(form, organization.paper_size).warnings
        if warnings and not confirm_despite_problems(self, check_heading, warnings):
            return None
        return form, organization

    def _after_printing(
        self, form: Form, organization: Organization, done: str
    ) -> None:
        # Printed sheets are scanned against this version, so it's kept as it is,
        # with the exact page templates that went to paper.
        layout = layout_form(form, organization.paper_size)
        mark_printed(
            self._connection, form.form_id, form.version, printed_layout(layout)
        )
        self._update_version_note(form)
        self.status_message.emit(
            tr(
                "{done}. Version {version} is now kept as printed; changes from here "
                "make version {next}."
            ).format(done=done, version=form.version, next=form.version + 1)
        )

    # --- Undo ---------------------------------------------------------------------

    def undo(self) -> None:
        """Ctrl+Z: put the form back as it was before the last change."""
        if not self._undo_stack:
            self.status_message.emit(tr("Nothing to undo."))
            return
        before, description = self._undo_stack.pop()
        self._redo_stack.append((self._snapshot(), description))
        self._restore(before)
        self.status_message.emit(tr("Undid: {change}.").format(change=description))

    def redo(self) -> None:
        """Ctrl+Shift+Z or Ctrl+Y: make the last undone change again."""
        if not self._redo_stack:
            self.status_message.emit(tr("Nothing to redo."))
            return
        after, description = self._redo_stack.pop()
        self._undo_stack.append((self._snapshot(), description))
        self._restore(after)
        self.status_message.emit(tr("Redid: {change}.").format(change=description))

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def _snapshot(self) -> _Snapshot:
        return _Snapshot(
            name=self.name_edit.text(),
            orientation=self.orientation_combo.currentData(),
            blocks=tuple(self._blocks),
            selected=tuple(self.selected_rows()),
        )

    def _reset_history(self) -> None:
        self._undo_stack: list[tuple[_Snapshot, str]] = []
        self._redo_stack: list[tuple[_Snapshot, str]] = []
        self._shown = self._snapshot()

    def _commit_change(self, description: str) -> None:
        """Remember the state before a change just made, so it can be undone."""
        now = self._snapshot()
        if now.content() == self._shown.content():
            self._shown = now
            return
        self._undo_stack.append((self._shown, description))
        self._redo_stack.clear()
        self._shown = now

    def _restore(self, snapshot: _Snapshot) -> None:
        with QSignalBlocker(self.name_edit), QSignalBlocker(self.orientation_combo):
            self.name_edit.setText(snapshot.name)
            self.orientation_combo.setCurrentIndex(
                self.orientation_combo.findData(snapshot.orientation)
            )
        self._blocks = list(snapshot.blocks)
        self._fill_block_list(list(snapshot.selected))
        self._shown = snapshot
        self.update_state()

    def _connect_blocks(self) -> None:
        self.orientation_combo.currentIndexChanged.connect(self.update_state)
        self.orientation_combo.currentIndexChanged.connect(
            lambda: self._commit_change(tr("changed the page orientation"))
        )
        # Typing is undone by the name field itself; leaving it records the rename.
        self.name_edit.editingFinished.connect(
            lambda: self._commit_change(tr("renamed the form"))
        )
        self.add_text_button.clicked.connect(lambda: self.add_block(BLOCK_KINDS.TEXT))
        self.add_question_button.clicked.connect(
            lambda: self.add_block(BLOCK_KINDS.QUESTION)
        )
        self.add_table_button.clicked.connect(lambda: self.add_block(BLOCK_KINDS.TABLE))
        self.edit_block_button.clicked.connect(self.edit_selected_block)
        self.remove_block_button.clicked.connect(self.remove_selected_blocks)
        self.move_up_button.clicked.connect(lambda: self.move_selected_blocks(-1))
        self.move_down_button.clicked.connect(lambda: self.move_selected_blocks(1))
        self.block_list.itemActivated.connect(lambda _item: self.edit_selected_block())
        self.block_list.itemSelectionChanged.connect(self._selection_changed)
        self.block_list.currentRowChanged.connect(
            lambda _row: self._update_block_controls()
        )
        self.new_page_check.toggled.connect(self._set_start_on_new_page)
        self.table_break_combo.activated.connect(self._set_table_break)
        remove_shortcut = add_shortcut(
            self.block_list,
            QKeySequence.StandardKey.Delete,
            self.remove_selected_blocks,
        )
        # Only from the blocks list (and the pages, which handle Delete
        # themselves); in a text field Delete deletes text.
        remove_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.shortcuts.append(remove_shortcut)
        self.shortcuts += add_standard_shortcuts(
            self, QKeySequence.StandardKey.Undo, self.undo
        )
        # Ctrl+Y redoes everywhere, though it is only the standard key on Windows.
        self.shortcuts += add_standard_shortcuts(
            self, QKeySequence.StandardKey.Redo, self.redo, "Ctrl+Y"
        )

    def _set_start_on_new_page(self, checked: bool) -> None:  # noqa: FBT001 (Qt signal)
        rows = self.selected_rows()
        if not rows:
            return
        for row in rows:
            self._blocks[row] = replace(self._blocks[row], start_on_new_page=checked)
        self._fill_block_list(rows, self.block_list.currentRow())
        self.update_state()
        self._commit_change(tr("changed where a block starts"))

    def _set_table_break(self, index: int) -> None:
        table_break = self.table_break_combo.itemData(index)
        rows = [
            row
            for row in self.selected_rows()
            if self._blocks[row].kind == BLOCK_KINDS.TABLE
        ]
        if not rows:
            return
        for row in rows:
            self._blocks[row] = replace(self._blocks[row], table_break=table_break)
        self._fill_block_list(self.selected_rows(), self.block_list.currentRow())
        self.update_state()
        self._commit_change(tr("changed how a table breaks across pages"))

    def _fill_block_list(
        self, select: Sequence[int], current: int | None = None
    ) -> None:
        with QSignalBlocker(self.block_list):
            self.block_list.clear()
            for number, block in enumerate(self._blocks, start=1):
                self.block_list.addItem(block_summary(number, block))
        self.set_selection(select, current)

    def _update_block_controls(self) -> None:
        rows = self.selected_rows()
        current = self.block_list.currentRow()
        block = self._blocks[current] if 0 <= current < len(self._blocks) else None
        single = len(rows) == 1
        self.edit_block_button.setEnabled(
            single and block is not None and block.kind in EDITABLE_KINDS
        )
        self.edit_block_button.setToolTip(
            tr("Tables are edited in the Tables section")
            if block is not None and block.kind == BLOCK_KINDS.TABLE
            else tr("Edit this form's copy of the block")
        )
        self.remove_block_button.setEnabled(bool(rows))
        self.remove_block_button.setText(
            tr("Remo&ve blocks") if len(rows) > 1 else tr("Remo&ve block")
        )
        moved_up, _ = move_by(self._blocks, rows, -1)
        moved_down, _ = move_by(self._blocks, rows, 1)
        self.move_up_button.setEnabled(bool(rows) and moved_up != self._blocks)
        self.move_down_button.setEnabled(bool(rows) and moved_down != self._blocks)
        with (
            QSignalBlocker(self.new_page_check),
            QSignalBlocker(self.table_break_combo),
        ):
            self.new_page_check.setEnabled(block is not None)
            self.new_page_check.setChecked(
                block is not None and block.start_on_new_page
            )
            tables = [
                row for row in rows if self._blocks[row].kind == BLOCK_KINDS.TABLE
            ]
            self.form.setRowVisible(self.table_break_combo, bool(tables))
            if tables:
                self.table_break_combo.setCurrentIndex(
                    self.table_break_combo.findData(self._blocks[tables[0]].table_break)
                )

    def _update_version_note(self, item: Form | None) -> None:
        if item is None or item.version == 0:
            self.version_note.setText(tr("Saving creates version 1."))
        elif is_printed(self._connection, item.form_id, item.version):
            self.version_note.setText(
                tr(
                    "Version {version} has been printed, so it is kept as it is; "
                    "saving changes creates version {next}."
                ).format(version=item.version, next=item.version + 1)
            )
        else:
            self.version_note.setText(
                tr(
                    "Version {version}. Changes are saved into it until it is printed."
                ).format(version=item.version)
            )


@dataclass(frozen=True)
class _Snapshot:
    """The form as it was at one moment, for undo and redo."""

    name: str
    orientation: str
    blocks: tuple[FormBlock, ...]
    selected: tuple[int, ...]

    def content(self) -> tuple[str, str, tuple[FormBlock, ...]]:
        """What counts as a change: everything but the selection."""
        return self.name, self.orientation, self.blocks


def _moved_description(moved: list[int]) -> str:
    return tr("moved %n block(s)", None, len(moved))


def _moved_status(moved: list[int], count: int) -> str:
    if len(moved) == 1:
        return tr("Moved to position {position} of {count}.").format(
            position=moved[0] + 1, count=count
        )
    return tr(
        "Moved %n block(s) to positions {first} to {last} of {count}.", None, len(moved)
    ).format(first=moved[0] + 1, last=moved[-1] + 1, count=count)


def _printer(form: Form, organization: Organization) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setPageLayout(page_layout_for(organization.paper_size, form.orientation))
    printer.setDocName(
        tr("{name} (version {version})").format(name=form.name, version=form.version)
    )
    return printer


def _file_name(name: str) -> str:
    """A form name made safe to use as a file name."""
    return re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .-") or "form"
