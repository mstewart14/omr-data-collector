from __future__ import annotations

import sqlite3
import uuid
from itertools import pairwise
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QTextListFormat
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.models.TextBlock import TextBlock, copy_name
from omr_data_collector.storage.text_block_store import (
    delete_text_block,
    list_text_blocks,
    save_text_block,
)
from omr_data_collector.ui.accessibility import set_field_error, style_error_label
from omr_data_collector.ui.form_helpers import (
    add_field_row,
    add_shortcut,
    ask_save_discard_cancel,
    confirm_destructive,
)
from omr_data_collector.ui.TextBlockEditor import HEADING_LEVELS, TextBlockEditor

if TYPE_CHECKING:
    from collections.abc import Callable

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


class TextBlocksPage(QWidget):
    """Create, save, edit, duplicate and delete reusable text blocks.

    Covers the "Create reusable text content block" epic on the wiki (stories
    10001-10005). The list on the left holds saved blocks; the editor on the right
    edits the selected one, or a new one after New.
    """

    status_message = Signal(str)

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__()
        self._connection = connection
        self._blocks: list[TextBlock] = []
        # The block being edited: a saved one, or None for a new, unsaved block,
        # which already has its permanent ID.
        self._current: TextBlock | None = None
        self._editing_id = uuid.uuid4().hex
        self._baseline_name = ""
        self._baseline_content = ""

        layout = QHBoxLayout(self)
        layout.addWidget(self._build_library_box(), stretch=1)
        layout.addWidget(self._build_editor_box(), stretch=3)
        self._connect_signals()
        self.initial_focus: QWidget = self.block_list

        self._reload_list()
        if self._blocks:
            self._select(self._blocks[0].text_block_id)
            self._edit(self._blocks[0])
        else:
            self._edit(None)

    # --- Public actions -------------------------------------------------------

    def has_unsaved_changes(self) -> bool:
        return (
            self.name_edit.text().strip() != self._baseline_name
            or self.editor.markdown() != self._baseline_content
        )

    def save(self) -> None:
        text_block = TextBlock(
            name=self.name_edit.text(),
            content=self.editor.markdown(),
            text_block_id=self._editing_id,
        ).normalized()
        other_names = {
            block.name
            for block in self._blocks
            if block.text_block_id != self._editing_id
        }
        errors = text_block.validation_errors(other_names)
        if not errors:
            try:
                save_text_block(self._connection, text_block)
            except sqlite3.IntegrityError:
                # Another window or process took the name since the list loaded.
                errors = {
                    "name": f'Another text block is already called "{text_block.name}".'
                }
        self._show_errors(errors)
        if errors:
            first_invalid = "name" if "name" in errors else "content"
            self.field_widgets[first_invalid].setFocus(Qt.FocusReason.OtherFocusReason)
            count = len(errors)
            self.status_message.emit(
                f"{count} field{'s' if count > 1 else ''} to fix before saving."
            )
            return

        self._reload_list()
        self._select(text_block.text_block_id)
        self._edit(text_block)
        self.status_message.emit(f'Text block "{text_block.name}" saved.')

    def revert(self) -> None:
        self._edit(self._current)

    def new_block(self) -> None:
        if not self._resolve_unsaved_changes():
            return
        self._select(None)
        self._edit(None)
        self.name_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self.status_message.emit("New text block. Enter a name and the text.")

    def duplicate_block(self) -> None:
        if self._current is None or not self._resolve_unsaved_changes():
            return
        original = self._current
        duplicate = TextBlock(
            name=copy_name(original.name, {block.name for block in self._blocks}),
            content=original.content,
        )
        save_text_block(self._connection, duplicate)
        self._reload_list()
        self._select(duplicate.text_block_id)
        self._edit(duplicate)
        self.name_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self.name_edit.selectAll()
        self.status_message.emit(f'Duplicated "{original.name}" as "{duplicate.name}".')

    def delete_block(self) -> None:
        if self._current is None:
            return
        doomed = self._current
        if not confirm_destructive(
            self,
            "Delete text block",
            f'Delete the text block "{doomed.name}"? This can\'t be undone.',
            "Delete",
        ):
            return
        row = self.block_list.currentRow()
        delete_text_block(self._connection, doomed.text_block_id)
        self._reload_list()
        if self._blocks:
            neighbour = self._blocks[min(row, len(self._blocks) - 1)]
            self._select(neighbour.text_block_id)
            self._edit(neighbour)
            self.block_list.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self._select(None)
            self._edit(None)
        self.status_message.emit(f'Text block "{doomed.name}" deleted.')

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt override)
        # A theme switch changes the background, so the error color is chosen again
        # to keep its contrast.
        if event.type() == QEvent.Type.PaletteChange:
            for label in self.error_labels.values():
                style_error_label(label, self.palette())
        super().changeEvent(event)

    # --- Layout -----------------------------------------------------------------

    def _build_library_box(self) -> QGroupBox:
        self.block_list = QListWidget()
        list_label = QLabel("Text &blocks")
        list_label.setBuddy(self.block_list)
        self.new_button = QPushButton("&New")
        self.new_button.setToolTip("Start a new text block (Ctrl+N)")
        self.duplicate_button = QPushButton("D&uplicate")
        self.duplicate_button.setToolTip("Save a copy of the selected text block")
        self.delete_button = QPushButton("&Delete")
        self.delete_button.setToolTip("Delete the selected text block (Delete key)")
        buttons = QHBoxLayout()
        for button in (self.new_button, self.duplicate_button, self.delete_button):
            buttons.addWidget(button)

        box = QGroupBox("Library")
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(list_label)
        box_layout.addWidget(self.block_list)
        box_layout.addLayout(buttons)
        return box

    def _build_editor_box(self) -> QGroupBox:
        self.name_edit = QLineEdit()
        self.style_combo = QComboBox()
        for label, level in PARAGRAPH_STYLES:
            self.style_combo.addItem(label, level)
        self.editor = TextBlockEditor()
        self.editor.setMinimumHeight(
            self.editor.fontMetrics().lineSpacing() * EDITOR_VISIBLE_LINES
        )

        self.bold_button = self._format_button("Bold", "Ctrl+B")
        self.italic_button = self._format_button("Italic", "Ctrl+I")
        self.bulleted_button = self._format_button(
            "Bulleted list", BULLETED_LIST_SHORTCUT
        )
        self.numbered_button = self._format_button(
            "Numbered list", NUMBERED_LIST_SHORTCUT
        )
        formatting = QWidget()
        formatting.setAccessibleName("Formatting")
        formatting_layout = QHBoxLayout(formatting)
        formatting_layout.setContentsMargins(0, 0, 0, 0)
        for button in (
            self.bold_button,
            self.italic_button,
            self.bulleted_button,
            self.numbered_button,
        ):
            formatting_layout.addWidget(button)
        formatting_layout.addStretch()

        self.form = QFormLayout()
        name_label, name_error = add_field_row(
            self.form, "Bloc&k name (required)", self.name_edit
        )
        style_label = QLabel("St&yle")
        style_label.setBuddy(self.style_combo)
        self.form.addRow(style_label, self.style_combo)
        self.form.addRow("Formatting", formatting)
        content_label, content_error = add_field_row(
            self.form, "&Text (required)", self.editor
        )
        self.field_widgets: dict[str, QWidget] = {
            "name": self.name_edit,
            "content": self.editor,
        }
        self.field_labels = {"name": name_label, "content": content_label}
        self.error_labels = {"name": name_error, "content": content_error}

        self.save_button = QPushButton("&Save")
        self.save_button.setDefault(True)
        self.save_button.setToolTip("Save the text block (Ctrl+S)")
        self.revert_button = QPushButton("&Revert")
        self.revert_button.setToolTip("Discard unsaved changes")
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.revert_button)
        buttons.addWidget(self.save_button)

        self.editor_box = QGroupBox()
        box_layout = QVBoxLayout(self.editor_box)
        box_layout.addLayout(self.form)
        box_layout.addLayout(buttons)
        return self.editor_box

    def _format_button(self, text: str, shortcut: str) -> QToolButton:
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

    def _connect_signals(self) -> None:
        self.save_button.clicked.connect(self.save)
        self.revert_button.clicked.connect(self.revert)
        self.new_button.clicked.connect(self.new_block)
        self.duplicate_button.clicked.connect(self.duplicate_block)
        self.delete_button.clicked.connect(self.delete_block)
        self.block_list.currentItemChanged.connect(self._on_selection_changed)
        self.name_edit.textChanged.connect(self._update_state)
        self.name_edit.returnPressed.connect(self.save)
        self.editor.textChanged.connect(self._update_state)
        self.editor.cursorPositionChanged.connect(self._sync_formatting_controls)
        self.editor.currentCharFormatChanged.connect(self._sync_formatting_controls)

        self.style_combo.activated.connect(self._apply_style)
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

        self.shortcuts = [
            add_shortcut(self, QKeySequence.StandardKey.Save, self.save),
            add_shortcut(self, QKeySequence.StandardKey.New, self.new_block),
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
        delete_shortcut = add_shortcut(
            self.block_list, QKeySequence.StandardKey.Delete, self.delete_block
        )
        # Only from the list: in the editor, Delete deletes text.
        delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.shortcuts.append(delete_shortcut)

        # Tab follows the screen: the library, then the editor top to bottom.
        focus_chain = [
            self.block_list,
            self.new_button,
            self.duplicate_button,
            self.delete_button,
            self.name_edit,
            self.style_combo,
            self.bold_button,
            self.italic_button,
            self.bulleted_button,
            self.numbered_button,
            self.editor,
            self.revert_button,
            self.save_button,
        ]
        for before, after in pairwise(focus_chain):
            QWidget.setTabOrder(before, after)

    # --- State --------------------------------------------------------------------

    def _reload_list(self) -> None:
        self._blocks = list_text_blocks(self._connection)
        with QSignalBlocker(self.block_list):
            self.block_list.clear()
            for block in self._blocks:
                item = QListWidgetItem(block.name)
                item.setData(Qt.ItemDataRole.UserRole, block.text_block_id)
                self.block_list.addItem(item)

    def _select(self, text_block_id: str | None) -> None:
        """Select a block in the list without treating it as the person's choice."""
        with QSignalBlocker(self.block_list):
            self.block_list.setCurrentRow(-1)
            for row in range(self.block_list.count()):
                item = self.block_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == text_block_id:
                    self.block_list.setCurrentRow(row)
                    break

    def _edit(self, text_block: TextBlock | None) -> None:
        """Load a saved block, or a blank new one, into the editor."""
        self._current = text_block
        self._editing_id = text_block.text_block_id if text_block else uuid.uuid4().hex
        self._show_errors({})
        with QSignalBlocker(self.name_edit), QSignalBlocker(self.editor):
            self.name_edit.setText(text_block.name if text_block else "")
            self.editor.set_markdown(text_block.content if text_block else "")
        self._baseline_name = self.name_edit.text().strip()
        # Compared with the editor's own Markdown, not the stored text, so that
        # Qt's formatting of the same content never counts as a change.
        self._baseline_content = self.editor.markdown()
        self.editor_box.setTitle(
            f'Editing "{text_block.name}"' if text_block else "New text block"
        )
        self._update_state()
        self._sync_formatting_controls()

    def _on_selection_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if current is None:
            return
        # Read now: saving below reloads the list, which deletes this item.
        text_block_id = current.data(Qt.ItemDataRole.UserRole)
        if not self._resolve_unsaved_changes():
            # Cancelled: put the selection back on the block still being edited.
            self._select(self._current.text_block_id if self._current else None)
            return
        self._select(text_block_id)
        self._edit(
            next(
                block for block in self._blocks if block.text_block_id == text_block_id
            )
        )

    def _resolve_unsaved_changes(self) -> bool:
        """Ask about unsaved changes before leaving them; False means stay."""
        if not self.has_unsaved_changes():
            return True
        answer = ask_save_discard_cancel(
            self, "Save your changes to this text block first?"
        )
        if answer == QMessageBox.StandardButton.Save:
            self.save()
            return not self.has_unsaved_changes()
        return answer == QMessageBox.StandardButton.Discard

    def _show_errors(self, errors: dict[str, str]) -> None:
        for field_name, label in self.error_labels.items():
            set_field_error(
                self.form,
                self.field_widgets[field_name],
                label,
                errors.get(field_name, ""),
            )

    def _update_state(self) -> None:
        unsaved = self.has_unsaved_changes()
        self.save_button.setEnabled(unsaved)
        self.revert_button.setEnabled(unsaved)
        saved = self._current is not None
        self.duplicate_button.setEnabled(saved)
        self.delete_button.setEnabled(saved)

    # --- Formatting -------------------------------------------------------------

    def _format(self, apply: Callable[[], None]) -> None:
        apply()
        self.editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self._sync_formatting_controls()

    def _apply_style(self, index: int) -> None:
        self._set_heading_level(self.style_combo.itemData(index))

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
