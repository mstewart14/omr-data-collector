from __future__ import annotations

from typing import TYPE_CHECKING

from omr_data_collector.i18n import tr
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.storage.text_block_store import (
    delete_text_block,
    list_text_blocks,
    save_text_block,
)
from omr_data_collector.ui.FormattedTextFields import FormattedTextFields
from omr_data_collector.ui.LibraryPage import LibraryPage, LibraryTexts

if TYPE_CHECKING:
    from PySide6.QtWidgets import QFormLayout, QWidget

EDITOR_VISIBLE_LINES = 12


class TextBlocksPage(LibraryPage):
    """Create, save, edit, duplicate and delete reusable text blocks.

    Covers the "Create reusable text content block" epic on the wiki (stories
    10001-10005).
    """

    COPIED_INTO_FORMS = True

    def texts(self) -> LibraryTexts:
        return LibraryTexts(
            list_label=tr("Text &blocks"),
            name_label=tr("Bloc&k name (required)"),
            new_title=tr("New text block"),
            new_status=tr("New text block. Enter a name and the text."),
            new_tooltip=tr("Start a new text block (Ctrl+N)"),
            duplicate_tooltip=tr("Save a copy of the selected text block"),
            delete_tooltip=tr("Delete the selected text block (Delete key)"),
            save_tooltip=tr("Save the text block (Ctrl+S)"),
            delete_title=tr("Delete text block"),
            delete_question=tr(
                'Delete the text block "{name}"? This can\'t be undone.'
            ),
            saved=tr('Text block "{name}" saved.'),
            deleted=tr('Text block "{name}" deleted.'),
            name_taken=tr('Another text block is already called "{name}".'),
            save_first=tr("Save your changes to this text block first?"),
        )

    def build_fields(self, form: QFormLayout) -> list[QWidget]:
        self.text_fields = FormattedTextFields(
            form,
            (self.field_widgets, self.field_labels, self.error_labels),
            key="content",
            text_label=tr("Te&xt (required)"),
            style_label=tr("St&yle"),
            visible_lines=EDITOR_VISIBLE_LINES,
            shortcut_parent=self,
            on_change=self.update_state,
        )
        self.shortcuts += self.text_fields.shortcuts
        return self.text_fields.focus_chain()

    def load_fields(self, item: TextBlock | None) -> None:
        self.text_fields.set_markdown(item.content if item is not None else "")

    def read_item(self, name: str, item_id: str) -> TextBlock:
        return TextBlock(
            name=name, content=self.text_fields.markdown(), text_block_id=item_id
        ).normalized()

    def list_items(self) -> list[TextBlock]:
        return list_text_blocks(self._connection)

    def store_item(self, item: TextBlock) -> None:
        save_text_block(self._connection, item)

    def remove_item(self, item_id: str) -> None:
        delete_text_block(self._connection, item_id)

    def copy_item(self, item: TextBlock, name: str) -> TextBlock:
        return TextBlock(name=name, content=item.content)

    def item_id(self, item: TextBlock) -> str:
        return item.text_block_id
