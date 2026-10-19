from __future__ import annotations

from typing import TYPE_CHECKING

from omr_data_collector.constants import PAGE_ORIENTATIONS
from omr_data_collector.i18n import tr
from omr_data_collector.models.Organization import paper_size_of
from omr_data_collector.models.TableBlock import TableBlock
from omr_data_collector.storage.organization_store import load_organization
from omr_data_collector.storage.table_block_store import (
    delete_table_block,
    list_table_blocks,
    save_table_block,
)
from omr_data_collector.ui.LibraryPage import LibraryPage, LibraryTexts
from omr_data_collector.ui.TableFields import TableFields

if TYPE_CHECKING:
    from PySide6.QtWidgets import QFormLayout, QWidget


class TableBlocksPage(LibraryPage[TableBlock]):
    """Create, save, edit, duplicate and delete reusable tables.

    Covers the "Create reusable data input table data collector block" epic on
    the wiki (stories 30001-30010), including previewing the table on a portrait
    or landscape page.
    """

    COPIED_INTO_FORMS = True

    def texts(self) -> LibraryTexts:
        return LibraryTexts(
            list_label=tr("Table li&brary"),
            name_label=tr("Na&me (required)"),
            new_title=tr("New table"),
            new_status=tr("New table. Enter a name, then add columns."),
            new_tooltip=tr("Start a new table (Ctrl+N)"),
            duplicate_tooltip=tr("Save a copy of the selected table"),
            delete_tooltip=tr("Delete the selected table (Delete key)"),
            save_tooltip=tr("Save the table (Ctrl+S)"),
            delete_title=tr("Delete table"),
            delete_question=tr('Delete the table "{name}"? This can\'t be undone.'),
            saved=tr('Table "{name}" saved.'),
            deleted=tr('Table "{name}" deleted.'),
            name_taken=tr('Another table is already called "{name}".'),
            save_first=tr("Save your changes to this table first?"),
        )

    def build_fields(self, form: QFormLayout) -> list[QWidget]:
        self.table_fields = TableFields(
            form,
            (self.field_widgets, self.field_labels, self.error_labels),
            shortcut_parent=self,
            on_change=self.update_state,
        )
        self.shortcuts += self.table_fields.shortcuts
        return self.table_fields.focus_chain()

    def load_fields(self, item: TableBlock | None) -> None:
        # Previewed on the organization's own orientation to start with.
        organization = load_organization(self._connection)
        self.table_fields.load(
            item,
            organization.orientation if organization else PAGE_ORIENTATIONS.PORTRAIT,
        )

    def read_item(self, name: str, item_id: str) -> TableBlock:
        return self.table_fields.table(name, item_id)

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
        self.table_fields.refresh(
            self.read_item(self.name_edit.text(), self._editing_id),
            paper_size_of(load_organization(self._connection)),
        )
