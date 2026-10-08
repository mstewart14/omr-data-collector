from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible, QTextCursor
from PySide6.QtWidgets import QAbstractSpinBox, QTableWidgetItem

from omr_data_collector.constants import (
    ANSWER_TYPES,
    CHECK_DIGIT_SCHEMES,
    WRITTEN_DATA_TYPES,
)
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Question import Question
from omr_data_collector.storage.question_store import list_questions, save_question
from omr_data_collector.ui.QuestionsPage import QuestionsPage

if TYPE_CHECKING:
    import sqlite3

    from pytestqt.qtbot import QtBot


def make_page(qtbot: QtBot, connection: sqlite3.Connection) -> QuestionsPage:
    page = QuestionsPage(connection)
    qtbot.addWidget(page)
    return page


def choose(combo, value: str) -> None:
    combo.setCurrentIndex(combo.findData(value))


def set_choice(page: QuestionsPage, row: int, label: str, output: str = "") -> None:
    table = page.answer_fields.choices_table
    table.setItem(row, 0, QTableWidgetItem(label))
    table.setItem(row, 1, QTableWidgetItem(output))


def row_visible(page: QuestionsPage, widget) -> bool:
    return page.form.isRowVisible(widget)


def test_new_question_starts_as_yes_no(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    fields = page.answer_fields

    assert fields.answer_type_combo.currentData() == ANSWER_TYPES.YES_NO
    assert fields.choices_table.rowCount() == 2
    assert not fields.add_choice_button.isEnabled()
    assert not row_visible(page, fields.characters_spin)


def test_create_a_yes_no_question(qtbot: QtBot, connection: sqlite3.Connection) -> None:
    page = make_page(qtbot, connection)
    page.name_edit.setText("first_visit")
    page.text_fields.editor.setPlainText("Is this your first visit?")
    page.example_edit.setText("Mark one")
    set_choice(page, 0, "Yes", "1")
    set_choice(page, 1, "No", "0")

    with qtbot.waitSignal(page.status_message) as status:
        page.save()

    (saved,) = list_questions(connection)
    assert saved.prompt.strip() == "Is this your first visit?"
    assert saved.answer.choices == (Choice("Yes", "1"), Choice("No", "0"))
    assert status.args == ['Question "first_visit" saved.']
    assert not page.has_unsaved_changes()


def test_create_a_list_question_with_added_reordered_choices(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    fields = page.answer_fields
    page.name_edit.setText("services")
    page.text_fields.editor.setPlainText("Which services did you use?")
    choose(fields.answer_type_combo, ANSWER_TYPES.MANY_CHOICES)
    assert fields.choices_table.rowCount() == 3
    for row, label in enumerate(("Clothing", "Food hamper", "Referral")):
        set_choice(page, row, label)
    fields.add_choice()
    set_choice(page, 3, "Other", "other")
    fields.choices_table.setCurrentCell(1, 0)
    fields.move_choice(-1)

    page.save()

    (saved,) = list_questions(connection)
    assert saved.answer.answer_type == ANSWER_TYPES.MANY_CHOICES
    assert [choice.label for choice in saved.answer.choices] == [
        "Food hamper",
        "Clothing",
        "Referral",
        "Other",
    ]
    assert saved.answer.choices[3].output == "other"


def test_remove_choice(qtbot: QtBot, connection: sqlite3.Connection) -> None:
    page = make_page(qtbot, connection)
    fields = page.answer_fields
    choose(fields.answer_type_combo, ANSWER_TYPES.ONE_CHOICE)
    for row, label in enumerate(("A", "B", "C")):
        set_choice(page, row, label)
    fields.choices_table.setCurrentCell(1, 0)

    fields.remove_choice()

    assert [choice.label for choice in fields.spec().choices] == ["A", "C"]


def test_switching_answer_types_keeps_each_types_choices(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    fields = page.answer_fields
    set_choice(page, 0, "Agree")
    set_choice(page, 1, "Disagree")

    choose(fields.answer_type_combo, ANSWER_TYPES.ONE_CHOICE)
    set_choice(page, 0, "Morning")
    choose(fields.answer_type_combo, ANSWER_TYPES.WRITTEN)
    choose(fields.answer_type_combo, ANSWER_TYPES.YES_NO)
    assert [choice.label for choice in fields.spec().choices] == ["Agree", "Disagree"]

    choose(fields.answer_type_combo, ANSWER_TYPES.ONE_CHOICE)
    assert fields.spec().choices[0].label == "Morning"


@pytest.mark.parametrize(
    ("data_type", "shown", "hidden"),
    [
        (WRITTEN_DATA_TYPES.FREE_TEXT, [], ["minimum_spin", "date_format_combo"]),
        (
            WRITTEN_DATA_TYPES.NUMBER,
            ["minimum_spin", "maximum_spin"],
            ["check_digit_combo"],
        ),
        (WRITTEN_DATA_TYPES.DATE_TIME, ["date_format_combo"], ["minimum_spin"]),
        (WRITTEN_DATA_TYPES.ID, ["check_digit_combo"], ["date_format_combo"]),
    ],
)
def test_written_answers_show_only_their_settings(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    data_type: str,
    shown: list[str],
    hidden: list[str],
) -> None:
    page = make_page(qtbot, connection)
    fields = page.answer_fields
    choose(fields.answer_type_combo, ANSWER_TYPES.WRITTEN)

    choose(fields.data_type_combo, data_type)

    assert not row_visible(page, fields.choices_table)
    assert row_visible(page, fields.characters_spin)
    for name in shown:
        assert row_visible(page, getattr(fields, name)), name
    for name in hidden:
        assert not row_visible(page, getattr(fields, name)), name


def test_date_format_sets_and_locks_the_character_count(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    fields = page.answer_fields
    choose(fields.answer_type_combo, ANSWER_TYPES.WRITTEN)
    choose(fields.data_type_combo, WRITTEN_DATA_TYPES.DATE_TIME)

    choose(fields.date_format_combo, "HH:MM")

    assert fields.characters_spin.value() == 5
    assert not fields.characters_spin.isEnabled()


@pytest.mark.parametrize(
    "answer",
    [
        AnswerSpec(
            ANSWER_TYPES.WRITTEN,
            data_type=WRITTEN_DATA_TYPES.NUMBER,
            max_characters=3,
            number_minimum=0,
            number_maximum=120,
        ),
        AnswerSpec(ANSWER_TYPES.WRITTEN, data_type=WRITTEN_DATA_TYPES.NUMBER),
        AnswerSpec(
            ANSWER_TYPES.WRITTEN,
            data_type=WRITTEN_DATA_TYPES.DATE_TIME,
            date_time_format="YYYY/MM/DD HH:MM",
        ),
        AnswerSpec(
            ANSWER_TYPES.WRITTEN,
            data_type=WRITTEN_DATA_TYPES.ID,
            max_characters=7,
            check_digit=CHECK_DIGIT_SCHEMES.DAMM,
        ),
        AnswerSpec(
            ANSWER_TYPES.ONE_CHOICE,
            choices=(Choice("A", "a"), Choice("B", "B"), Choice("C", "see")),
        ),
    ],
)
def test_saved_answers_load_back_without_unsaved_changes(
    qtbot: QtBot, connection: sqlite3.Connection, answer: AnswerSpec
) -> None:
    question = Question(name="q", prompt="?", answer=answer)
    save_question(connection, question)

    page = make_page(qtbot, connection)

    assert page.answer_fields.spec() == answer.normalized()
    assert not page.has_unsaved_changes()


def test_choice_errors_focus_the_choices_table(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    with qtbot.waitActive(page):
        page.show()
        page.activateWindow()
    page.name_edit.setText("services")
    page.text_fields.editor.setPlainText("Which?")
    choose(page.answer_fields.answer_type_combo, ANSWER_TYPES.ONE_CHOICE)
    set_choice(page, 0, "A")

    page.save()

    assert page.error_labels["choices"].text() == "Choice 2 needs words to print."
    assert page.focusWidget() is page.answer_fields.choices_table
    assert list_questions(connection) == []


def test_number_range_error_is_shown_under_maximum(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    fields = page.answer_fields
    page.name_edit.setText("age")
    page.text_fields.editor.setPlainText("Age?")
    choose(fields.answer_type_combo, ANSWER_TYPES.WRITTEN)
    choose(fields.data_type_combo, WRITTEN_DATA_TYPES.NUMBER)
    fields.minimum_spin.setValue(10)
    fields.maximum_spin.setValue(5)

    page.save()

    assert page.form.isRowVisible(page.error_labels["number_maximum"])


def test_duplicate_copies_the_answer(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    answer = AnswerSpec(
        ANSWER_TYPES.YES_NO, choices=(Choice("Yes", "1"), Choice("No", "0"))
    )
    save_question(
        connection, Question(name="visit", prompt="First visit?", answer=answer)
    )
    page = make_page(qtbot, connection)

    page.duplicate_item()

    copy = next(q for q in list_questions(connection) if q.name == "visit (copy)")
    assert copy.answer == answer
    assert copy.prompt == "First visit?"


# --- Accessibility ----------------------------------------------------------------


def test_every_field_is_labelled_for_screen_readers(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)

    for key, label in page.field_labels.items():
        interface = QAccessible.queryAccessibleInterface(page.field_widgets[key])
        labels = [
            related.text(QAccessible.Text.Name)
            for related, _ in interface.relations(QAccessible.RelationFlag.Label)
        ]
        assert labels[0] == label.text().replace("&", ""), key


def test_every_validation_error_has_somewhere_to_show(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    possible_errors = {
        "name",
        "prompt",
        "answer_type",
        "choices",
        "data_type",
        "max_characters",
        "number_maximum",
        "date_time_format",
        "check_digit",
    }

    assert possible_errors <= set(page.error_labels)


def test_tab_leaves_the_choices_table_instead_of_moving_between_cells(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)

    assert not page.answer_fields.choices_table.tabKeyNavigation()
    assert page.text_fields.editor.tabChangesFocus()


def test_tab_order_follows_the_screen(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    fields = page.answer_fields
    expected = [
        page.item_list,
        page.new_button,
        page.duplicate_button,
        page.delete_button,
        page.name_edit,
        page.text_fields.style_combo,
        page.text_fields.bold_button,
        page.text_fields.italic_button,
        page.text_fields.bulleted_button,
        page.text_fields.numbered_button,
        page.text_fields.editor,
        page.example_edit,
        fields.answer_type_combo,
        fields.choices_table,
        fields.add_choice_button,
        fields.remove_choice_button,
        fields.move_up_button,
        fields.move_down_button,
        fields.data_type_combo,
        fields.characters_spin,
        fields.minimum_spin,
        fields.maximum_spin,
        fields.date_format_combo,
        fields.check_digit_combo,
        page.revert_button,
        page.save_button,
    ]

    # Tab passes over widgets that don't take keyboard focus, and treats a spin
    # box and the text field inside it as one stop.
    chain = [expected[0]]
    widget = expected[0]
    while len(chain) < len(expected):
        widget = widget.nextInFocusChain()
        inside_spin_box = isinstance(widget.parentWidget(), QAbstractSpinBox)
        if widget.focusPolicy() & Qt.FocusPolicy.TabFocus and not inside_spin_box:
            chain.append(widget)

    assert chain == expected


def test_no_limit_is_spoken_as_words_not_a_number(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)

    assert page.answer_fields.minimum_spin.text() == "No minimum"
    assert page.answer_fields.maximum_spin.text() == "No maximum"


def test_question_text_can_be_formatted(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    page.name_edit.setText("consent")
    page.text_fields.editor.setPlainText("Do you consent?")
    cursor = page.text_fields.editor.textCursor()
    cursor.select(QTextCursor.SelectionType.Document)
    page.text_fields.editor.setTextCursor(cursor)
    page.text_fields.bold_button.click()

    page.save()

    (saved,) = list_questions(connection)
    assert saved.prompt.strip() == "**Do you consent?**"
    page.item_list.setCurrentRow(0)
    assert not page.has_unsaved_changes()
