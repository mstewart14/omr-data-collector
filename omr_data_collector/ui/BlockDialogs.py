"""Dialogs the form builder uses to pick a library block, or write a block's copy."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.constants import ANSWER_TYPES, BLOCK_KINDS
from omr_data_collector.models.AnswerSpec import AnswerSpec
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.ui.accessibility import set_field_error, style_error_label
from omr_data_collector.ui.AnswerFields import AnswerFields
from omr_data_collector.ui.form_helpers import add_field_row
from omr_data_collector.ui.FormattedTextFields import FormattedTextFields

if TYPE_CHECKING:
    from collections.abc import Sequence

    from omr_data_collector.models.Form import BlockContent

TEXT_VISIBLE_LINES = 8
PROMPT_VISIBLE_LINES = 4


class BlockPickerDialog(QDialog):
    """Choose a library block to copy onto a form, or choose to write a new one."""

    def __init__(
        self,
        parent: QWidget | None,
        noun: str,
        items: Sequence[BlockContent],
        *,
        can_write_new: bool,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Add {noun}")
        self._items = list(items)
        self.write_new = False

        self.item_list = QListWidget()
        for item in self._items:
            self.item_list.addItem(item.name)
        if self._items:
            self.item_list.setCurrentRow(0)
        label = QLabel(f"&{noun.capitalize()}s in the library")
        label.setBuddy(self.item_list)
        self.empty_note = QLabel(
            f"There are no {noun}s in the library yet."
            + (
                f" Write a new {noun}, or add some in the library first."
                if can_write_new
                else ""
            )
        )
        self.empty_note.setWordWrap(True)
        self.empty_note.setVisible(not self._items)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setText("Add copy")
        ok_button.setEnabled(bool(self._items))
        self.write_new_button: QPushButton | None = None
        if can_write_new:
            self.write_new_button = self.buttons.addButton(
                f"&Write a new {noun}…", QDialogButtonBox.ButtonRole.ActionRole
            )
            self.write_new_button.clicked.connect(self._choose_write_new)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.item_list.itemActivated.connect(lambda _item: self.accept())

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.item_list)
        layout.addWidget(self.empty_note)
        layout.addWidget(self.buttons)
        self.item_list.setFocus(Qt.FocusReason.OtherFocusReason)

    def chosen(self) -> BlockContent | None:
        """The library block picked, or None (for Write a new one, or nothing)."""
        if self.write_new:
            return None
        row = self.item_list.currentRow()
        return self._items[row] if row >= 0 else None

    def _choose_write_new(self) -> None:
        self.write_new = True
        self.accept()


class BlockContentDialog(QDialog):
    """Write a new text block or question on a form, or edit a form's own copy.

    Only the form's copy changes; the library block it came from doesn't.
    """

    def __init__(
        self, parent: QWidget | None, kind: str, content: BlockContent | None
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self._content_id = (
            content.text_block_id
            if isinstance(content, TextBlock)
            else content.question_id
            if isinstance(content, Question)
            else None
        )
        self._accepted: BlockContent | None = None
        noun = "text block" if kind == BLOCK_KINDS.TEXT else "question"
        self.setWindowTitle(
            f"Edit {noun} on this form" if content else f"Write a new {noun}"
        )

        self.form = QFormLayout()
        self.field_widgets: dict[str, QWidget] = {}
        self.field_labels: dict[str, QLabel] = {}
        self.error_labels: dict[str, QLabel] = {}
        self.name_edit = QLineEdit()
        self.field_labels["name"], self.error_labels["name"] = add_field_row(
            self.form, "Na&me (required)", self.name_edit
        )
        self.field_widgets["name"] = self.name_edit
        registry = (self.field_widgets, self.field_labels, self.error_labels)
        focus_chain: list[QWidget] = [self.name_edit]

        if kind == BLOCK_KINDS.TEXT:
            self.text_fields = FormattedTextFields(
                self.form,
                registry,
                key="content",
                text_label="Te&xt (required)",
                style_label="St&yle",
                visible_lines=TEXT_VISIBLE_LINES,
                shortcut_parent=self,
                on_change=lambda: None,
            )
            focus_chain += self.text_fields.focus_chain()
        else:
            self.text_fields = FormattedTextFields(
                self.form,
                registry,
                key="prompt",
                text_label="Questi&on (required)",
                style_label="Sty&le",
                visible_lines=PROMPT_VISIBLE_LINES,
                shortcut_parent=self,
                on_change=lambda: None,
            )
            self.example_edit = QLineEdit()
            self.field_labels["example"], self.error_labels["example"] = add_field_row(
                self.form, "&Example or instructions", self.example_edit
            )
            self.field_widgets["example"] = self.example_edit
            self.answer_fields = AnswerFields(
                self.form,
                self.field_widgets,
                self.field_labels,
                self.error_labels,
                lambda: None,
            )
            focus_chain += [
                *self.text_fields.focus_chain(),
                self.example_edit,
                *self.answer_fields.focus_chain(),
            ]

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.buttons)
        for before, after in pairwise([*focus_chain, *self.buttons.buttons()]):
            QWidget.setTabOrder(before, after)

        self._load(content)
        self.name_edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def entered_content(self) -> BlockContent:
        """The block as currently entered, normalized; an edited copy keeps its ID."""
        if self._kind == BLOCK_KINDS.TEXT:
            text = TextBlock(
                name=self.name_edit.text(), content=self.text_fields.markdown()
            )
            if self._content_id:
                text = replace(text, text_block_id=self._content_id)
            return text.normalized()
        question = Question(
            name=self.name_edit.text(),
            prompt=self.text_fields.markdown(),
            example=self.example_edit.text(),
            answer=self.answer_fields.spec(),
        )
        if self._content_id:
            question = replace(question, question_id=self._content_id)
        return question.normalized()

    def content(self) -> BlockContent | None:
        """The accepted block; None until OK is pressed with valid settings."""
        return self._accepted

    def accept(self) -> None:
        content = self.entered_content()
        errors = content.validation_errors(set())
        for key, label in self.error_labels.items():
            set_field_error(
                self.form, self.field_widgets[key], label, errors.get(key, "")
            )
        if errors:
            first = next(key for key in self.field_widgets if key in errors)
            self.field_widgets[first].setFocus(Qt.FocusReason.OtherFocusReason)
            return
        self._accepted = content
        super().accept()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.PaletteChange:
            for label in self.error_labels.values():
                style_error_label(label, self.palette())
        super().changeEvent(event)

    def _load(self, content: BlockContent | None) -> None:
        if isinstance(content, TextBlock):
            self.name_edit.setText(content.name)
            self.text_fields.set_markdown(content.content)
        elif isinstance(content, Question):
            self.name_edit.setText(content.name)
            self.text_fields.set_markdown(content.prompt)
            self.example_edit.setText(content.example)
            self.answer_fields.set_spec(content.answer)
        elif self._kind == BLOCK_KINDS.QUESTION:
            self.answer_fields.set_spec(AnswerSpec.default(ANSWER_TYPES.YES_NO))
