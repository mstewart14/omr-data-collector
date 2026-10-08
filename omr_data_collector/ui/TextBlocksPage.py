from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QFont, QKeySequence, QTextListFormat
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QToolButton, QWidget

from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.storage.text_block_store import (
    delete_text_block,
    list_text_blocks,
    save_text_block,
)
from omr_data_collector.ui.form_helpers import add_field_row, add_shortcut
from omr_data_collector.ui.LibraryPage import LibraryPage
from omr_data_collector.ui.TextBlockEditor import HEADING_LEVELS, TextBlockEditor

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QFormLayout

# Paragraph styles in the Style box: label and heading level (0 = ordinary text).
PARAGRAPH_STYLES = (
    ("Normal text", 0),
    *((f"Heading {level}", level) for level in HEADING_LEVELS),
)
# Shortcuts follow common word processors (Google Docs, LibreOffice).
HEADING_SHORTCUTS = {level: f"Ctrl+Alt+{level}" for level in (0, *HEADING_LEVELS)}
BULLETED_LIST_SHORTCUT = "Ctrl+Shift+8"
NUMBERED_LIST_SHORTCUT = "Ctrl+Shift+7"
EDITOR_VISIBLE_LINES = 12


class TextBlocksPage(LibraryPage):
    """Create, save, edit, duplicate and delete reusable text blocks.

    Covers the "Create reusable text content block" epic on the wiki (stories
    10001-10005).
    """

    NOUN = "text block"
    LIST_LABEL = "Text &blocks"
    NAME_LABEL = "Bloc&k name (required)"
    NEW_HINT = "Enter a name and the text."

    def build_fields(self, form: QFormLayout) -> list[QWidget]:
        self.style_combo = QComboBox()
        for label, level in PARAGRAPH_STYLES:
            self.style_combo.addItem(label, level)
        self.editor = TextBlockEditor()
        self.editor.setMinimumHeight(
            self.editor.fontMetrics().lineSpacing() * EDITOR_VISIBLE_LINES
        )

        self.bold_button = _format_button("Bold", "Ctrl+B")
        self.italic_button = _format_button("Italic", "Ctrl+I")
        self.bulleted_button = _format_button("Bulleted list", BULLETED_LIST_SHORTCUT)
        self.numbered_button = _format_button("Numbered list", NUMBERED_LIST_SHORTCUT)
        format_buttons = (
            self.bold_button,
            self.italic_button,
            self.bulleted_button,
            self.numbered_button,
        )
        formatting = QWidget()
        formatting.setAccessibleName("Formatting")
        formatting_layout = QHBoxLayout(formatting)
        formatting_layout.setContentsMargins(0, 0, 0, 0)
        for button in format_buttons:
            formatting_layout.addWidget(button)
        formatting_layout.addStretch()

        style_label = QLabel("St&yle")
        style_label.setBuddy(self.style_combo)
        form.addRow(style_label, self.style_combo)
        form.addRow("Formatting", formatting)
        content_label, content_error = add_field_row(
            form, "&Text (required)", self.editor
        )
        self.field_widgets["content"] = self.editor
        self.field_labels["content"] = content_label
        self.error_labels["content"] = content_error

        self._connect_formatting()
        return [self.style_combo, *format_buttons, self.editor]

    def load_fields(self, item: TextBlock | None) -> None:
        with QSignalBlocker(self.editor):
            self.editor.set_markdown(item.content if item is not None else "")
        self._sync_formatting_controls()

    def read_item(self, name: str, item_id: str) -> TextBlock:
        return TextBlock(
            name=name, content=self.editor.markdown(), text_block_id=item_id
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

    # --- Formatting -------------------------------------------------------------

    def _connect_formatting(self) -> None:
        self.editor.textChanged.connect(self.update_state)
        self.editor.cursorPositionChanged.connect(self._sync_formatting_controls)
        self.editor.currentCharFormatChanged.connect(self._sync_formatting_controls)
        self.style_combo.activated.connect(
            lambda index: self._set_heading_level(self.style_combo.itemData(index))
        )
        self.bold_button.clicked.connect(
            lambda checked: self._format(lambda: self.editor.set_bold(on=checked))
        )
        self.italic_button.clicked.connect(
            lambda checked: self._format(lambda: self.editor.set_italic(on=checked))
        )
        self.bulleted_button.clicked.connect(
            lambda: self._format(
                lambda: self.editor.toggle_list(QTextListFormat.Style.ListDisc)
            )
        )
        self.numbered_button.clicked.connect(
            lambda: self._format(
                lambda: self.editor.toggle_list(QTextListFormat.Style.ListDecimal)
            )
        )
        self.shortcuts += [
            add_shortcut(self, "Ctrl+B", self.bold_button.click),
            add_shortcut(self, "Ctrl+I", self.italic_button.click),
            add_shortcut(self, BULLETED_LIST_SHORTCUT, self.bulleted_button.click),
            add_shortcut(self, NUMBERED_LIST_SHORTCUT, self.numbered_button.click),
            *(
                add_shortcut(
                    self, key, lambda level=level: self._set_heading_level(level)
                )
                for level, key in HEADING_SHORTCUTS.items()
            ),
        ]

    def _format(self, apply: Callable[[], None]) -> None:
        apply()
        self.editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self._sync_formatting_controls()

    def _set_heading_level(self, level: int) -> None:
        self._format(lambda: self.editor.set_heading_level(level))

    def _sync_formatting_controls(self) -> None:
        """Show the formatting at the cursor, so the checked state is announced."""
        char_format = self.editor.currentCharFormat()
        list_style = self.editor.list_style()
        controls = (
            self.style_combo,
            self.bold_button,
            self.italic_button,
            self.bulleted_button,
            self.numbered_button,
        )
        blockers = [QSignalBlocker(control) for control in controls]
        self.style_combo.setCurrentIndex(
            self.style_combo.findData(self.editor.heading_level())
        )
        # Heading text is bold by its style, not by the Bold button.
        heading = self.editor.heading_level() > 0
        self.bold_button.setChecked(
            not heading and char_format.fontWeight() >= QFont.Weight.Bold.value
        )
        self.italic_button.setChecked(char_format.fontItalic())
        self.bulleted_button.setChecked(list_style == QTextListFormat.Style.ListDisc)
        self.numbered_button.setChecked(list_style == QTextListFormat.Style.ListDecimal)
        del blockers


def _format_button(text: str, shortcut: str) -> QToolButton:
    button = QToolButton()
    button.setText(text)
    button.setCheckable(True)
    # Reachable with Tab like any other control; QToolButton defaults to
    # mouse-only focus.
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    shortcut_text = QKeySequence(shortcut).toString(
        QKeySequence.SequenceFormat.NativeText
    )
    button.setToolTip(f"{text} ({shortcut_text})")
    button.setAccessibleDescription(f"Shortcut: {shortcut_text}")
    return button
