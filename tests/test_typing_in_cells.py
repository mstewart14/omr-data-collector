"""What is being typed in a table cell counts when saving, whatever is clicked.

On macOS clicking a button doesn't take focus from the cell being typed in,
and a shortcut like Ctrl+S never does, so the cell's editor is still open
when the page or dialog reads the table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLineEdit

from omr_data_collector.constants import ANSWER_TYPES
from omr_data_collector.storage.question_store import list_questions
from omr_data_collector.ui.ColumnDialog import ColumnDialog
from omr_data_collector.ui.QuestionsPage import QuestionsPage

if TYPE_CHECKING:
    import sqlite3

    from pytestqt.qtbot import QtBot

    from omr_data_collector.ui.AnswerFields import AnswerFields


def type_choices_leaving_the_last_open(
    qtbot: QtBot, fields: AnswerFields, words: list[str]
) -> None:
    """Fill in the choices, the last still being typed when the reading starts."""
    fields.answer_type_combo.setCurrentIndex(
        fields.answer_type_combo.findData(ANSWER_TYPES.ONE_CHOICE)
    )
    *done, last = words
    for row, word in enumerate(done):
        item = fields.choices_table.item(row, 0)
        assert item is not None
        item.setText(word)
    while fields.choices_table.rowCount() > len(done):
        fields.choices_table.removeRow(fields.choices_table.rowCount() - 1)
    fields.add_choice()
    (editor,) = [
        child
        for child in fields.choices_table.viewport().findChildren(QLineEdit)
        if child.isVisible()
    ]
    qtbot.keyClicks(editor, last)


def test_saving_a_question_keeps_the_choice_being_typed(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = QuestionsPage(connection)
    qtbot.addWidget(page)
    page.show()
    page.name_edit.setText("colour")
    page.text_fields.editor.setPlainText("Favourite colour?")
    type_choices_leaving_the_last_open(
        qtbot, page.answer_fields, ["Red", "Green", "Blue"]
    )

    assert page.save()

    (question,) = list_questions(connection)
    assert [choice.label for choice in question.answer.choices] == [
        "Red",
        "Green",
        "Blue",
    ]


def test_ok_on_a_column_keeps_the_choice_being_typed(qtbot: QtBot) -> None:
    dialog = ColumnDialog(None, None, set())
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.name_edit.setText("service")
    type_choices_leaving_the_last_open(
        qtbot, dialog.answer_fields, ["Food", "Clothing", "Referral"]
    )

    dialog.accept()

    column = dialog.column()
    assert column is not None
    assert [choice.label for choice in column.answer.choices] == [
        "Food",
        "Clothing",
        "Referral",
    ]
