from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QAbstractSpinBox, QTableWidgetItem

from omr_data_collector.constants import (
    ANSWER_TYPES,
    BLOCK_KINDS,
    CAPTURE_STATUSES,
    PAGE_ORIENTATIONS,
    TABLE_BREAKS,
)
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.storage.capture_store import add_capture, save_capture
from omr_data_collector.storage.form_store import list_forms, mark_printed, save_form
from omr_data_collector.storage.question_store import save_question
from omr_data_collector.storage.table_block_store import save_table_block
from omr_data_collector.storage.text_block_store import save_text_block
from omr_data_collector.ui.BlockDialogs import BlockContentDialog, BlockPickerDialog
from omr_data_collector.ui.FormsPage import FormsPage, block_summary

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

PAGE_MODULE = "omr_data_collector.ui.FormsPage"

TITLE = TextBlock(name="Title", content="# Client intake\n")
VISIT = Question(
    name="first_visit",
    prompt="Is this your first visit?",
    answer=AnswerSpec(ANSWER_TYPES.YES_NO, choices=(Choice("Yes"), Choice("No"))),
).normalized()
LOG = TableBlock(
    name="Visit log",
    columns=(
        Column("time", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=5)),
    ),
)


def make_page(qtbot: QtBot, connection: sqlite3.Connection) -> FormsPage:
    page = FormsPage(connection)
    qtbot.addWidget(page)
    return page


def picks(mocker: MockerFixture, *answers: tuple[bool, object]):
    return mocker.patch(f"{PAGE_MODULE}.pick_block", side_effect=list(answers))


def writes(mocker: MockerFixture, *contents: object):
    return mocker.patch(f"{PAGE_MODULE}.write_block", side_effect=list(contents))


def blocks(page: FormsPage) -> list[FormBlock]:
    return list(page.read_item("f", "x" * 32).blocks)


def saved_intake(connection: sqlite3.Connection, *, printed: bool = False) -> Form:
    form = save_form(
        connection,
        Form(
            name="Intake",
            blocks=(
                FormBlock(TITLE, TITLE.text_block_id),
                FormBlock(VISIT, None),
                FormBlock(LOG, LOG.table_block_id),
            ),
        ).normalized(),
    )
    if printed:
        mark_printed(connection, form.form_id, form.version)
    return form


# --- Building a form ------------------------------------------------------------


def test_add_copies_of_library_blocks(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_text_block(connection, TITLE)
    save_table_block(connection, LOG)
    page = make_page(qtbot, connection)
    page.name_edit.setText("Intake")
    pick = picks(mocker, (True, TITLE), (True, LOG))

    page.add_block(BLOCK_KINDS.TEXT)
    page.add_block(BLOCK_KINDS.TABLE)

    library_offered = pick.call_args_list[0].args[2]
    assert [item.name for item in library_offered] == ["Title"]
    assert [(block.kind, block.source_id) for block in blocks(page)] == [
        (BLOCK_KINDS.TEXT, TITLE.text_block_id),
        (BLOCK_KINDS.TABLE, LOG.table_block_id),
    ]


def test_write_a_new_question_on_the_form(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    page = make_page(qtbot, connection)
    picks(mocker, (True, None))
    writes(mocker, VISIT)

    page.add_block(BLOCK_KINDS.QUESTION)

    (block,) = blocks(page)
    assert block.content == VISIT
    assert block.source_id is None
    assert "written on this form" in page.block_list.item(0).text()


@pytest.mark.parametrize(
    "answers",
    [((False, None),), ((True, None),)],
    ids=["picker cancelled", "writer cancelled"],
)
def test_cancelling_adds_nothing(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    answers: tuple,
) -> None:
    page = make_page(qtbot, connection)
    picks(mocker, *answers)
    writes(mocker, None)

    page.add_block(BLOCK_KINDS.TEXT)

    assert blocks(page) == []


def test_new_blocks_go_under_the_selected_one(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    saved_intake(connection)
    page = make_page(qtbot, connection)
    page.block_list.setCurrentRow(0)
    footer = TextBlock(name="Footer", content="Thanks")
    picks(mocker, (True, footer))

    page.add_block(BLOCK_KINDS.TEXT)

    assert [block.content.name for block in blocks(page)] == [
        "Title",
        "Footer",
        "first_visit",
        "Visit log",
    ]
    assert page.block_list.currentRow() == 1


def test_edit_the_forms_copy_of_a_question(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_question(connection, VISIT)
    saved_intake(connection)
    page = make_page(qtbot, connection)
    page.block_list.setCurrentRow(1)
    reworded = Question(
        VISIT.name,
        "First time here?",
        answer=VISIT.answer,
        question_id=VISIT.question_id,
    )
    write = writes(mocker, reworded)

    page.edit_selected_block()

    assert write.call_args.args[1:] == (BLOCK_KINDS.QUESTION, VISIT)
    edited = blocks(page)[1].content
    assert isinstance(edited, Question)
    assert edited.prompt == "First time here?"
    assert page.has_unsaved_changes()


def test_table_copies_are_not_edited_on_the_form(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    saved_intake(connection)
    page = make_page(qtbot, connection)
    write = writes(mocker)

    page.block_list.setCurrentRow(2)
    page.edit_selected_block()

    write.assert_not_called()
    assert not page.edit_block_button.isEnabled()
    assert page.edit_block_button.toolTip() == "Tables are edited in the Tables section"


def test_remove_and_reorder_blocks(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    saved_intake(connection)
    page = make_page(qtbot, connection)

    page.block_list.setCurrentRow(2)
    page.move_selected_blocks(-1)
    assert [block.content.name for block in blocks(page)] == [
        "Title",
        "Visit log",
        "first_visit",
    ]
    page.block_list.setCurrentRow(0)
    page.remove_selected_blocks()
    assert [block.content.name for block in blocks(page)] == [
        "Visit log",
        "first_visit",
    ]


def test_page_options_for_the_selected_block(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    saved_intake(connection)
    page = make_page(qtbot, connection)

    page.block_list.setCurrentRow(1)
    assert not page.form.isRowVisible(page.table_break_combo)
    page.new_page_check.setChecked(True)

    page.block_list.setCurrentRow(2)
    assert page.form.isRowVisible(page.table_break_combo)
    page.table_break_combo.activated.emit(
        page.table_break_combo.findData(TABLE_BREAKS.NEW_PAGE)
    )

    question, table = blocks(page)[1], blocks(page)[2]
    assert question.start_on_new_page
    assert table.table_break == TABLE_BREAKS.NEW_PAGE
    assert "moves to a new page if it doesn't fit" in page.block_list.item(2).text()


def test_save_a_new_form(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    page = make_page(qtbot, connection)
    page.name_edit.setText("Intake")
    page.orientation_combo.setCurrentIndex(
        page.orientation_combo.findData(PAGE_ORIENTATIONS.LANDSCAPE)
    )
    picks(mocker, (True, TITLE))
    page.add_block(BLOCK_KINDS.TEXT)

    with qtbot.waitSignal(page.status_message) as status:
        page.save()

    (saved,) = list_forms(connection)
    assert saved.version == 1
    assert saved.orientation == PAGE_ORIENTATIONS.LANDSCAPE
    assert status.args == ['Form "Intake" saved as version 1.']
    assert page.version_note.text() == (
        "Version 1. Changes are saved into it until it is printed."
    )
    assert not page.has_unsaved_changes()


def test_changing_a_printed_form_makes_a_new_version(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    saved_intake(connection, printed=True)
    page = make_page(qtbot, connection)
    assert page.version_note.text().startswith("Version 1 has been printed")

    page.block_list.setCurrentRow(0)
    page.remove_selected_blocks()
    page.save()

    (latest,) = list_forms(connection)
    assert latest.version == 2
    assert [block.content.name for block in latest.blocks] == [
        "first_visit",
        "Visit log",
    ]


def test_duplicate_questions_on_a_form_block_saving(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    page = make_page(qtbot, connection)
    page.name_edit.setText("Twice")
    picks(mocker, (True, VISIT), (True, VISIT))
    page.add_block(BLOCK_KINDS.QUESTION)
    page.add_block(BLOCK_KINDS.QUESTION)

    page.save()

    assert "both questions called" in page.error_labels["blocks"].text()
    assert list_forms(connection) == []


def test_duplicate_gives_the_copy_its_own_blocks(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    original = saved_intake(connection, printed=True)
    page = make_page(qtbot, connection)

    page.duplicate_item()

    copy = next(form for form in list_forms(connection) if form.name == "Intake (copy)")
    assert copy.version == 1
    assert [block.content for block in copy.blocks] == [
        block.content for block in original.blocks
    ]
    assert {block.block_id for block in copy.blocks}.isdisjoint(
        {block.block_id for block in original.blocks}
    )


def test_deleting_a_printed_form_warns_its_sheets_cant_be_scanned(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    saved_intake(connection, printed=True)
    page = make_page(qtbot, connection)
    confirm = mocker.patch(
        "omr_data_collector.ui.LibraryPage.confirm_destructive", return_value=False
    )

    page.delete_item()

    assert "can no longer be scanned" in confirm.call_args.args[2]


def test_deleting_a_form_with_captured_sheets_says_their_data_is_lost(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    form = saved_intake(connection, printed=True)
    image = tmp_path / "sheet.jpg"
    image.write_bytes(b"a sheet")
    save_capture(
        connection,
        replace(
            add_capture(connection, image),
            status=CAPTURE_STATUSES.SAVED,
            form_id=form.form_id,
            form_version=form.version,
            page=1,
        ),
    )
    page = make_page(qtbot, connection)
    confirm = mocker.patch(
        "omr_data_collector.ui.LibraryPage.confirm_destructive", return_value=False
    )

    page.delete_item()

    question = confirm.call_args.args[2]
    assert "1 sheet captured from it" in question
    assert "no longer be checked or exported" in question
    assert list_forms(connection) != []


def test_block_summaries() -> None:
    table = FormBlock(LOG, LOG.table_block_id, start_on_new_page=True)

    assert block_summary(3, table) == (
        "3. Table: Visit log (from the library, starts a new page, "
        "splits across pages if it doesn't fit)"
    )


# --- Keyboard and screen readers --------------------------------------------------


def test_delete_in_the_blocks_list_removes_a_block_not_the_form(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    saved_intake(connection)
    page = make_page(qtbot, connection)
    with qtbot.waitActive(page):
        page.show()
        page.activateWindow()
    confirm = mocker.patch(
        "omr_data_collector.ui.LibraryPage.confirm_destructive", return_value=False
    )
    page.block_list.setFocus()
    page.block_list.setCurrentRow(0)

    qtbot.keyClick(page.block_list, Qt.Key.Key_Delete)

    confirm.assert_not_called()
    assert len(blocks(page)) == 2


def test_fields_are_labelled(qtbot: QtBot, connection: sqlite3.Connection) -> None:
    page = make_page(qtbot, connection)
    for key, label in page.field_labels.items():
        interface = QAccessible.queryAccessibleInterface(page.field_widgets[key])
        labels = [
            related.text(QAccessible.Text.Name)
            for related, _ in interface.relations(QAccessible.RelationFlag.Label)
        ]
        assert labels[0] == label.text().replace("&", ""), key


def test_tab_order_follows_the_screen(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    # Left to right: the palette, then the form's details; the library list and
    # its buttons are hidden here (forms open from File > Open form).
    expected = [
        *page.block_palette.focus_chain(),
        page.name_edit,
        page.orientation_combo,
        page.sheet_details_combo,
        page.edit_details_button,
        page.block_list,
        page.add_text_button,
        page.add_question_button,
        page.add_table_button,
        page.edit_block_button,
        page.remove_block_button,
        page.move_up_button,
        page.move_down_button,
        page.new_page_check,
        # (If the table doesn't fit is hidden until a table is selected.)
        page.revert_button,
        page.save_button,
    ]

    chain = [expected[0]]
    widget = expected[0]
    while len(chain) < len(expected):
        widget = widget.nextInFocusChain()
        inside_spin_box = isinstance(widget.parentWidget(), QAbstractSpinBox)
        # Tab skips hidden widgets, such as the hidden library list.
        hidden = not widget.isVisibleTo(page)
        if (
            widget.focusPolicy() & Qt.FocusPolicy.TabFocus
            and not inside_spin_box
            and not hidden
        ):
            chain.append(widget)

    assert chain == expected


# --- Dialogs ----------------------------------------------------------------------


def test_picker_returns_the_chosen_library_block(qtbot: QtBot) -> None:
    dialog = BlockPickerDialog(None, BLOCK_KINDS.TEXT, [TITLE], can_write_new=True)
    qtbot.addWidget(dialog)

    dialog.accept()

    assert dialog.chosen() == TITLE


def test_picker_can_choose_to_write_a_new_one(qtbot: QtBot) -> None:
    dialog = BlockPickerDialog(None, BLOCK_KINDS.QUESTION, [VISIT], can_write_new=True)
    qtbot.addWidget(dialog)

    assert dialog.write_new_button is not None
    dialog.write_new_button.click()

    assert dialog.write_new
    assert dialog.chosen() is None


def test_picker_for_tables_offers_only_the_library(qtbot: QtBot) -> None:
    dialog = BlockPickerDialog(None, BLOCK_KINDS.TABLE, [], can_write_new=False)
    qtbot.addWidget(dialog)

    assert dialog.write_new_button is None
    assert not dialog.empty_note.isHidden()
    assert dialog.empty_note.text() == "There are no tables in the library yet."


def test_writing_a_new_text_block(qtbot: QtBot) -> None:
    dialog = BlockContentDialog(None, BLOCK_KINDS.TEXT, None)
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("Footer")
    dialog.text_fields.editor.setPlainText("Thank you")

    dialog.accept()

    content = dialog.content()
    assert isinstance(content, TextBlock)
    assert (content.name, content.content.strip()) == ("Footer", "Thank you")


def test_editing_a_question_copy_keeps_its_id_and_checks_it(qtbot: QtBot) -> None:
    dialog = BlockContentDialog(None, BLOCK_KINDS.QUESTION, VISIT)
    qtbot.addWidget(dialog)
    dialog.answer_fields.choices_table.setItem(0, 0, QTableWidgetItem(""))

    dialog.accept()
    assert dialog.content() is None
    assert dialog.error_labels["choices"].text() == '"Marked" needs words.'

    dialog.answer_fields.choices_table.setItem(0, 0, QTableWidgetItem("Yes"))
    dialog.accept()
    content = dialog.content()
    assert isinstance(content, Question)
    assert content.question_id == VISIT.question_id
