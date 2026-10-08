from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit

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
from omr_data_collector.ui.LibraryPage import LibraryPage

if TYPE_CHECKING:
    from PySide6.QtWidgets import QFormLayout, QWidget

PROMPT_VISIBLE_LINES = 3


class QuestionsPage(LibraryPage):
    """Create, save, edit, duplicate and delete reusable questions.

    Covers the "Create reusable data input question data collector block" epic
    on the wiki (stories 40001-40010).
    """

    NOUN = "question"
    LIST_LABEL = "Question &library"
    NAME_LABEL = "Na&me (required)"
    NEW_HINT = "Enter a name, the question and how it is answered."

    def build_fields(self, form: QFormLayout) -> list[QWidget]:
        self.name_edit.setToolTip("Also the column name when data is exported")
        self.prompt_edit = QPlainTextEdit()
        # Tab moves on rather than typing a tab, so keyboard users can leave.
        self.prompt_edit.setTabChangesFocus(True)
        self.prompt_edit.setFixedHeight(
            self.prompt_edit.fontMetrics().lineSpacing() * PROMPT_VISIBLE_LINES
            + 2 * self.prompt_edit.frameWidth()
            + int(2 * self.prompt_edit.document().documentMargin())
        )
        self.prompt_edit.setPlaceholderText(
            "As printed, like: Is this your first visit?"
        )
        self.example_edit = QLineEdit()
        self.example_edit.setPlaceholderText(
            "Printed with the question, like: Mark one"
        )

        for key, label_text, widget in (
            ("prompt", "&Question (required)", self.prompt_edit),
            ("example", "&Example or instructions", self.example_edit),
        ):
            self.field_labels[key], self.error_labels[key] = add_field_row(
                form, label_text, widget
            )
            self.field_widgets[key] = widget
        self.prompt_edit.textChanged.connect(self.update_state)
        self.example_edit.textChanged.connect(self.update_state)

        self.answer_fields = AnswerFields(
            form,
            self.field_widgets,
            self.field_labels,
            self.error_labels,
            self.update_state,
        )
        return [self.prompt_edit, self.example_edit, *self.answer_fields.focus_chain()]

    def load_fields(self, item: Question | None) -> None:
        with QSignalBlocker(self.prompt_edit), QSignalBlocker(self.example_edit):
            self.prompt_edit.setPlainText(item.prompt if item is not None else "")
            self.example_edit.setText(item.example if item is not None else "")
        self.answer_fields.set_spec(
            item.answer if item is not None else AnswerSpec.default(ANSWER_TYPES.YES_NO)
        )

    def read_item(self, name: str, item_id: str) -> Question:
        return Question(
            name=name,
            prompt=self.prompt_edit.toPlainText(),
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
