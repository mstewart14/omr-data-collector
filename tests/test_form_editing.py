"""Selecting several blocks, the Delete key, and undo/redo in the form editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QByteArray, QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent

from omr_data_collector.constants import (
    ANSWER_TYPES,
    BLOCK_KINDS,
    PAGE_ORIENTATIONS,
    TABLE_BREAKS,
)
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.storage.form_store import save_form
from omr_data_collector.storage.text_block_store import save_text_block
from omr_data_collector.ui.FormsPage import FormsPage
from omr_data_collector.ui.MainWindow import MainWindow
from omr_data_collector.ui.PageCanvas import FORM_BLOCK_MIME

if TYPE_CHECKING:
    import sqlite3

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


def text(name: str) -> FormBlock:
    return FormBlock(TextBlock(name=name, content=f"{name} text"))


def five_blocks() -> Form:
    return Form(
        name="Intake", blocks=tuple(text(name) for name in "ABCDE")
    ).normalized()


@pytest.fixture
def page(qtbot: QtBot, connection: sqlite3.Connection) -> FormsPage:
    save_form(connection, five_blocks())
    editor = FormsPage(connection)
    qtbot.addWidget(editor)
    editor.resize(1300, 900)
    with qtbot.waitActive(editor):
        editor.show()
        editor.activateWindow()
    return editor


def names(page: FormsPage) -> str:
    return "".join(block.content.name for block in page.read_item("f", "x" * 32).blocks)


def centre_of(page: FormsPage, index: int):
    area = next(area for area in page.canvas._areas if area.index == index)  # noqa: SLF001
    return area.rect.center().toPoint()


def click_block(
    qtbot: QtBot, page: FormsPage, index: int, modifiers=Qt.KeyboardModifier.NoModifier
) -> None:
    qtbot.mouseClick(
        page.canvas, Qt.MouseButton.LeftButton, modifiers, centre_of(page, index)
    )


# --- Selecting several ------------------------------------------------------------


def test_ctrl_click_adds_and_removes_blocks_from_the_selection(
    qtbot: QtBot, page: FormsPage
) -> None:
    click_block(qtbot, page, 1)
    click_block(qtbot, page, 3, CTRL)
    assert page.selected_rows() == [1, 3]
    assert page.canvas.selected_indices == {1, 3}

    click_block(qtbot, page, 1, CTRL)
    assert page.selected_rows() == [3]


def test_shift_click_selects_a_range(qtbot: QtBot, page: FormsPage) -> None:
    click_block(qtbot, page, 1)
    click_block(qtbot, page, 3, SHIFT)

    assert page.selected_rows() == [1, 2, 3]


def test_a_plain_click_selects_one_block(qtbot: QtBot, page: FormsPage) -> None:
    page.set_selection([0, 1, 2])

    click_block(qtbot, page, 4)

    assert page.selected_rows() == [4]


def test_clicking_empty_paper_clears_the_selection(
    qtbot: QtBot, page: FormsPage
) -> None:
    page.set_selection([0, 1])

    qtbot.mouseClick(
        page.canvas, Qt.MouseButton.LeftButton, pos=QPointF(5, 5).toPoint()
    )

    assert page.canvas.selected_indices == set()


def test_outline_selection_shows_on_the_pages(page: FormsPage) -> None:
    page.set_selection([0, 4])

    assert page.canvas.selected_indices == {0, 4}
    assert page.remove_block_button.text() == "Remo&ve blocks"
    assert not page.edit_block_button.isEnabled()  # edits one block at a time


# --- Acting on several ------------------------------------------------------------


def test_remove_several_blocks(page: FormsPage) -> None:
    page.set_selection([1, 3])

    with_status = []
    page.status_message.connect(with_status.append)
    page.remove_selected_blocks()

    assert names(page) == "ACE"
    assert with_status[-1] == "Removed 2 blocks. Ctrl+Z undoes it."


def test_move_several_blocks_up_and_down_together(page: FormsPage) -> None:
    page.set_selection([1, 3])

    page.move_selected_blocks(-1)
    assert names(page) == "BADCE"
    assert page.selected_rows() == [0, 2]

    page.move_selected_blocks(-1)  # B is at the top; D closes up to it
    assert names(page) == "BDACE"
    assert not page.move_up_button.isEnabled()


def test_dragging_a_selected_block_carries_the_whole_selection(page: FormsPage) -> None:
    page.set_selection([0, 2])
    mime = QMimeData()
    mime.setData(FORM_BLOCK_MIME, QByteArray(b"[0, 2]"))
    last = next(area for area in page.canvas._areas if area.index == 4)  # noqa: SLF001
    event = QDropEvent(
        QPointF(last.rect.center().x(), last.rect.bottom() - 1),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    page.canvas.dropEvent(event)

    assert names(page) == "BDEAC"
    assert page.selected_rows() == [3, 4]


def test_new_page_setting_applies_to_every_selected_block(page: FormsPage) -> None:
    page.set_selection([1, 2])

    page.new_page_check.setChecked(True)

    starts = [block.start_on_new_page for block in page.read_item("f", "x" * 32).blocks]
    assert starts == [False, True, True, False, False]


def test_table_break_applies_to_the_selected_tables(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    table = TableBlock(
        name="T", columns=(Column("c", answer=AnswerSpec(ANSWER_TYPES.WRITTEN)),)
    )
    save_form(
        connection,
        Form(
            name="Tables",
            blocks=(FormBlock(table), text("A"), FormBlock(table, block_id="b" * 32)),
        ),
    )
    editor = FormsPage(connection)
    qtbot.addWidget(editor)
    editor.open_item(
        next(form.form_id for form in editor.items() if form.name == "Tables")
    )
    editor.set_selection([0, 1, 2])

    editor.table_break_combo.activated.emit(
        editor.table_break_combo.findData(TABLE_BREAKS.NEW_PAGE)
    )

    breaks = [block.table_break for block in editor.read_item("f", "x" * 32).blocks]
    assert breaks == [TABLE_BREAKS.NEW_PAGE, TABLE_BREAKS.SPLIT, TABLE_BREAKS.NEW_PAGE]


# --- Delete key -------------------------------------------------------------------


def test_delete_key_on_the_pages_removes_the_selection(
    qtbot: QtBot, page: FormsPage
) -> None:
    click_block(qtbot, page, 0)
    click_block(qtbot, page, 4, CTRL)

    qtbot.keyClick(page.canvas, Qt.Key.Key_Delete)

    assert names(page) == "BCD"


def test_delete_key_in_the_outline_removes_the_selection(
    qtbot: QtBot, page: FormsPage
) -> None:
    page.block_list.setFocus()
    page.set_selection([2, 3])

    qtbot.keyClick(page.block_list, Qt.Key.Key_Delete)

    assert names(page) == "ABE"


def test_delete_key_in_the_name_field_deletes_text_not_blocks(
    qtbot: QtBot, page: FormsPage
) -> None:
    page.set_selection([0])
    page.name_edit.setFocus()
    page.name_edit.setCursorPosition(0)

    qtbot.keyClick(page.name_edit, Qt.Key.Key_Delete)

    assert page.name_edit.text() == "ntake"
    assert names(page) == "ABCDE"
    page.revert()


# --- Undo and redo ----------------------------------------------------------------


def test_ctrl_z_undoes_and_ctrl_shift_z_redoes(qtbot: QtBot, page: FormsPage) -> None:
    page.set_selection([1, 2])
    page.remove_selected_blocks()
    page.block_list.setFocus()

    statuses = []
    page.status_message.connect(statuses.append)
    qtbot.keyClick(page.block_list, Qt.Key.Key_Z, CTRL)
    assert names(page) == "ABCDE"
    assert page.selected_rows() == [1, 2]
    assert statuses[-1] == "Undid: removed 2 blocks."

    qtbot.keyClick(page.block_list, Qt.Key.Key_Z, CTRL | SHIFT)
    assert names(page) == "ADE"
    assert statuses[-1] == "Redid: removed 2 blocks."

    qtbot.keyClick(page.block_list, Qt.Key.Key_Z, CTRL)
    qtbot.keyClick(page.block_list, Qt.Key.Key_Y, CTRL)
    assert names(page) == "ADE"
    page.revert()


def test_undo_steps_back_through_every_kind_of_change(
    page: FormsPage, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    footer = TextBlock(name="Footer", content="Thanks")
    save_text_block(connection, footer)
    first = page.read_item("f", "x" * 32).blocks[0].content
    assert isinstance(first, TextBlock)
    edited = TextBlock(name="A2", content="edited", text_block_id=first.text_block_id)
    mocker.patch("omr_data_collector.ui.FormsPage.write_block", return_value=edited)

    page.add_library_block(BLOCK_KINDS.TEXT, footer.text_block_id, 5)  # ABCDE Footer
    page.set_selection([0])
    page.edit_selected_block()  # A2 BCDE Footer
    page.move_blocks_to([5], 0)  # Footer A2 BCDE
    page.orientation_combo.setCurrentIndex(
        page.orientation_combo.findData(PAGE_ORIENTATIONS.LANDSCAPE)
    )
    page.name_edit.setText("Renamed")
    page.name_edit.editingFinished.emit()

    history = []
    for _ in range(5):
        page.undo()
        history.append(
            (names(page), page.orientation_combo.currentData(), page.name_edit.text())
        )

    assert history == [
        ("FooterA2BCDE", PAGE_ORIENTATIONS.LANDSCAPE, "Intake"),
        ("FooterA2BCDE", PAGE_ORIENTATIONS.PORTRAIT, "Intake"),
        ("A2BCDEFooter", PAGE_ORIENTATIONS.PORTRAIT, "Intake"),
        ("ABCDEFooter", PAGE_ORIENTATIONS.PORTRAIT, "Intake"),
        ("ABCDE", PAGE_ORIENTATIONS.PORTRAIT, "Intake"),
    ]
    assert not page.has_unsaved_changes()


def test_a_new_change_clears_redo(page: FormsPage) -> None:
    page.set_selection([0])
    page.remove_selected_blocks()
    page.undo()
    assert page.can_redo()

    page.set_selection([4])
    page.move_selected_blocks(-1)

    assert not page.can_redo()
    page.revert()


def test_nothing_to_undo_says_so(page: FormsPage) -> None:
    statuses = []
    page.status_message.connect(statuses.append)

    page.undo()
    page.redo()

    assert statuses == ["Nothing to undo.", "Nothing to redo."]


def test_selection_alone_is_not_a_change(page: FormsPage) -> None:
    page.set_selection([1, 2])
    page.set_selection([3])

    assert not page.can_undo()


def test_opening_another_form_starts_a_fresh_history(
    page: FormsPage, connection: sqlite3.Connection
) -> None:
    other = save_form(connection, Form(name="Other", blocks=(text("Z"),)))
    page.set_selection([0])
    page.remove_selected_blocks()
    page.save()

    page._reload_list()  # noqa: SLF001 (pick up the form saved behind its back)
    page.open_item(other.form_id)

    assert not page.can_undo()


def test_ctrl_z_in_the_name_field_undoes_typing_first(
    qtbot: QtBot, page: FormsPage
) -> None:
    page.set_selection([0])
    page.remove_selected_blocks()
    page.name_edit.setFocus()
    qtbot.keyClicks(page.name_edit, "x")

    qtbot.keyClick(page.name_edit, Qt.Key.Key_Z, CTRL)

    assert page.name_edit.text() == "Intake"
    assert names(page) == "BCDE"  # the block stays removed
    page.revert()


def test_file_menu_undo_and_redo(qtbot: QtBot, connection: sqlite3.Connection) -> None:
    save_form(connection, five_blocks())
    window = MainWindow(connection)
    qtbot.addWidget(window)
    forms = window.forms_page
    forms.set_selection([0])
    forms.remove_selected_blocks()
    undo, redo = (
        next(
            action
            for action in window.file_menu.actions()
            if action.text().startswith(prefix)
        )
        for prefix in ("U&ndo", "Re&do")
    )

    window.file_menu.aboutToShow.emit()
    assert undo.isEnabled()
    assert not redo.isEnabled()
    undo.trigger()

    assert names(forms) == "ABCDE"
    assert window.stack.currentWidget() is forms
    window.file_menu.aboutToShow.emit()
    assert redo.isEnabled()


def test_question_blocks_work_the_same(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    question = Question(
        name="q",
        prompt="?",
        answer=AnswerSpec(ANSWER_TYPES.YES_NO, choices=(Choice("Y"), Choice("N"))),
    ).normalized()
    save_form(connection, Form(name="Q", blocks=(FormBlock(question), text("A"))))
    editor = FormsPage(connection)
    qtbot.addWidget(editor)
    editor.open_item(next(form.form_id for form in editor.items() if form.name == "Q"))
    editor.set_selection([0, 1])

    editor.remove_selected_blocks()
    editor.undo()

    assert names(editor) == "qA"
