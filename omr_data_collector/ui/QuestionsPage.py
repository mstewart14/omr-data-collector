from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QLineEdit

from omr_data_collector.constants import ANSWER_TYPES
from omr_data_collector.models.AnswerSpec import AnswerSpec
from omr_data_collector.models.Question import Question
from omr_data_collector.storage.question_store import (
    delete_question,
    list_questions,
    save_question,
)
from omr_data_collector.ui.AnswerFields import AnswerFields
from omr_data_collector.ui.form_helpers import add_field_row
from omr_data_collector.ui.FormattedTextFields import FormattedTextFields
from omr_data_collector.ui.LibraryPage import LibraryPage

if TYPE_CHECKING:
    from PySide6.QtWidgets import QFormLayout, QWidget

PROMPT_VISIBLE_LINES = 4


class QuestionsPage(LibraryPage):
    """Create, save, edit, duplicate and delete reusable questions.

    Covers the "Create reusable data input question data collector block" epic
    on the wiki (stories 40001-40010).
    """

    NOUN = "question"
    LIST_LABEL = "Question li&brary"
    NAME_LABEL = "Na&me (required)"
    NEW_HINT = "Enter a name, the question and how it is answered."

    def build_fields(self, form: QFormLayout) -> list[QWidget]:
        self.name_edit.setToolTip("Also the column name when data is exported")
        self.text_fields = FormattedTextFields(
            form,
            (self.field_widgets, self.field_labels, self.error_labels),
            key="prompt",
            text_label="&Question (required)",
            # Not "St&yle": Alt+Y is the answer's Data type on this page.
            style_label="Sty&le",
            visible_lines=PROMPT_VISIBLE_LINES,
            shortcut_parent=self,
            on_change=self.update_state,
        )
        self.shortcuts += self.text_fields.shortcuts
        self.text_fields.editor.setPlaceholderText(
            "As printed, like: Is this your first visit?"
        )
        self.example_edit = QLineEdit()
        self.example_edit.setPlaceholderText(
            "Printed with the question, like: Mark one"
        )
        self.field_labels["example"], self.error_labels["example"] = add_field_row(
            form, "&Example or instructions", self.example_edit
        )
        self.field_widgets["example"] = self.example_edit
        self.example_edit.textChanged.connect(self.update_state)

        self.answer_fields = AnswerFields(
            form,
            self.field_widgets,
            self.field_labels,
            self.error_labels,
            self.update_state,
        )
        return [
            *self.text_fields.focus_chain(),
            self.example_edit,
            *self.answer_fields.focus_chain(),
        ]

    def load_fields(self, item: Question | None) -> None:
        self.text_fields.set_markdown(item.prompt if item is not None else "")
        with QSignalBlocker(self.example_edit):
            self.example_edit.setText(item.example if item is not None else "")
        self.answer_fields.set_spec(
            item.answer if item is not None else AnswerSpec.default(ANSWER_TYPES.YES_NO)
        )

    def read_item(self, name: str, item_id: str) -> Question:
        return Question(
            name=name,
            prompt=self.text_fields.markdown(),
            example=self.example_edit.text(),
            answer=self.answer_fields.spec(),
            question_id=item_id,
        ).normalized()

    def list_items(self) -> list[Question]:
        return list_questions(self._connection)

    def store_item(self, item: Question) -> None:
        save_question(self._connection, item)

    def remove_item(self, item_id: str) -> None:
        delete_question(self._connection, item_id)

    def copy_item(self, item: Question, name: str) -> Question:
        return Question(
            name=name, prompt=item.prompt, example=item.example, answer=item.answer
        )

    def item_id(self, item: Question) -> str:
        return item.question_id
