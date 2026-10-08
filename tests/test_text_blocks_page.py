from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible, QTextCursor
from PySide6.QtWidgets import QMessageBox

from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.storage.text_block_store import (
    list_text_blocks,
    save_text_block,
)
from omr_data_collector.ui.TextBlocksPage import TextBlocksPage

if TYPE_CHECKING:
    import sqlite3

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

# The dialogs are asked by the shared library page.
PAGE_MODULE = "omr_data_collector.ui.LibraryPage"


def make_page(qtbot: QtBot, connection: sqlite3.Connection) -> TextBlocksPage:
    page = TextBlocksPage(connection)
    qtbot.addWidget(page)
    return page


def shown_page(qtbot: QtBot, connection: sqlite3.Connection) -> TextBlocksPage:
    page = make_page(qtbot, connection)
    with qtbot.waitActive(page):
        page.show()
        page.activateWindow()
    return page


def list_names(page: TextBlocksPage) -> list[str]:
    return [page.item_list.item(row).text() for row in range(page.item_list.count())]


def answer_unsaved(mocker: MockerFixture, answer: QMessageBox.StandardButton):
    return mocker.patch(f"{PAGE_MODULE}.ask_save_discard_cancel", return_value=answer)


def test_starts_on_a_new_block_when_there_are_none(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)

    assert page.item_list.count() == 0
    assert page.editor_box.title() == "New text block"
    assert not page.duplicate_button.isEnabled()
    assert not page.delete_button.isEnabled()
    assert not page.save_button.isEnabled()


def test_opens_the_first_saved_block(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    save_text_block(connection, TextBlock(name="Title", content="# Intake\n"))
    save_text_block(connection, TextBlock(name="Footer", content="Thanks"))

    page = make_page(qtbot, connection)

    assert list_names(page) == ["Footer", "Title"]
    assert page.name_edit.text() == "Footer"
    assert page.editor_box.title() == 'Editing "Footer"'
    assert not page.has_unsaved_changes()


def test_create_and_save_a_formatted_block(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    page.name_edit.setText(" Instructions ")
    page.editor.setPlainText("Fill in one bubble per row")
    cursor = page.editor.textCursor()
    cursor.select(QTextCursor.SelectionType.Document)
    page.editor.setTextCursor(cursor)
    page.bold_button.click()

    with qtbot.waitSignal(page.status_message) as status:
        page.save()

    assert list_text_blocks(connection) == [
        TextBlock(
            name="Instructions",
            content="**Fill in one bubble per row**\n\n",
            text_block_id=list_text_blocks(connection)[0].text_block_id,
        )
    ]
    assert status.args == ['Text block "Instructions" saved.']
    assert list_names(page) == ["Instructions"]
    assert page.item_list.currentItem().text() == "Instructions"
    assert page.delete_button.isEnabled()


def test_save_reports_missing_and_duplicate_names(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    save_text_block(connection, TextBlock(name="Footer", content="Thanks"))
    page = shown_page(qtbot, connection)
    page.new_item()

    page.save()
    assert page.error_labels["name"].text() == "Enter a name for the text block."
    assert page.error_labels["content"].text() == "Enter the text for the block."
    assert page.focusWidget() is page.name_edit

    page.name_edit.setText("footer")
    page.editor.setPlainText("More thanks")
    page.save()
    assert page.error_labels["name"].text() == (
        'Another text block is already called "footer".'
    )
    assert len(list_text_blocks(connection)) == 1


def test_edit_and_revert(qtbot: QtBot, connection: sqlite3.Connection) -> None:
    save_text_block(connection, TextBlock(name="Footer", content="Thanks"))
    page = make_page(qtbot, connection)

    page.editor.setPlainText("Thank you for coming")
    assert page.has_unsaved_changes()
    page.revert()
    assert page.editor.toPlainText() == "Thanks"

    page.editor.setPlainText("Thank you for coming")
    page.save()
    assert list_text_blocks(connection)[0].content.strip() == "Thank you for coming"


def test_duplicate_saves_a_renamed_copy_and_selects_it(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    original = TextBlock(name="Footer", content="Thanks")
    save_text_block(connection, original)
    page = make_page(qtbot, connection)

    with qtbot.waitSignal(page.status_message) as status:
        page.duplicate_item()

    names = sorted(block.name for block in list_text_blocks(connection))
    assert names == ["Footer", "Footer (copy)"]
    assert page.name_edit.text() == "Footer (copy)"
    assert page.item_list.currentItem().text() == "Footer (copy)"
    assert status.args == ['Duplicated "Footer" as "Footer (copy)".']


def test_delete_asks_first_and_moves_to_the_next_block(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    for name in ("A", "B", "C"):
        save_text_block(connection, TextBlock(name=name, content="x"))
    page = make_page(qtbot, connection)
    page.item_list.setCurrentRow(1)
    confirm = mocker.patch(f"{PAGE_MODULE}.confirm_destructive", return_value=False)

    page.delete_item()
    assert list_names(page) == ["A", "B", "C"]

    confirm.return_value = True
    page.delete_item()

    assert list_names(page) == ["A", "C"]
    assert page.name_edit.text() == "C"
    assert "can't be undone" in confirm.call_args.args[2]


def test_deleting_the_last_block_leaves_a_new_one(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_text_block(connection, TextBlock(name="Only", content="x"))
    page = make_page(qtbot, connection)
    mocker.patch(f"{PAGE_MODULE}.confirm_destructive", return_value=True)

    page.delete_item()

    assert page.item_list.count() == 0
    assert page.editor_box.title() == "New text block"


@pytest.mark.parametrize(
    ("answer", "switched", "saved_text"),
    [
        (QMessageBox.StandardButton.Save, True, "Edited"),
        (QMessageBox.StandardButton.Discard, True, "Original"),
        (QMessageBox.StandardButton.Cancel, False, "Original"),
    ],
)
def test_switching_blocks_asks_about_unsaved_changes(  # noqa: PLR0913
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    answer: QMessageBox.StandardButton,
    switched: bool,  # noqa: FBT001
    saved_text: str,
) -> None:
    save_text_block(connection, TextBlock(name="A", content="Original"))
    save_text_block(connection, TextBlock(name="B", content="Other"))
    page = make_page(qtbot, connection)
    page.editor.setPlainText("Edited")
    answer_unsaved(mocker, answer)

    page.item_list.setCurrentRow(1)

    assert (page.name_edit.text() == "B") == switched
    assert page.item_list.currentItem().text() == ("B" if switched else "A")
    stored = {
        block.name: block.content.strip() for block in list_text_blocks(connection)
    }
    assert stored["A"] == saved_text


def test_new_with_unsaved_changes_can_be_cancelled(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_text_block(connection, TextBlock(name="A", content="Original"))
    page = make_page(qtbot, connection)
    page.editor.setPlainText("Edited")
    answer_unsaved(mocker, QMessageBox.StandardButton.Cancel)

    page.new_item()

    assert page.name_edit.text() == "A"
    assert page.editor.toPlainText() == "Edited"


def test_formatting_buttons_follow_the_cursor(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    save_text_block(
        connection,
        TextBlock(name="A", content="## Title\n\n**bold** plain\n\n- item\n"),
    )
    page = make_page(qtbot, connection)

    page.editor.setTextCursor(QTextCursor(page.editor.document().findBlockByNumber(0)))
    assert page.style_combo.currentText() == "Heading 2"
    assert not page.bold_button.isChecked()  # heading text is bold by its style

    cursor = QTextCursor(page.editor.document().findBlockByNumber(1))
    cursor.movePosition(QTextCursor.MoveOperation.Right)
    page.editor.setTextCursor(cursor)
    assert page.style_combo.currentText() == "Normal text"
    assert page.bold_button.isChecked()

    page.editor.setTextCursor(QTextCursor(page.editor.document().findBlockByNumber(2)))
    assert page.bulleted_button.isChecked()
    assert not page.numbered_button.isChecked()


def test_style_box_sets_headings(qtbot: QtBot, connection: sqlite3.Connection) -> None:
    page = make_page(qtbot, connection)
    page.editor.setPlainText("Title")

    page.style_combo.activated.emit(page.style_combo.findText("Heading 1"))

    assert page.editor.markdown().startswith("# Title")


# --- Keyboard and screen readers --------------------------------------------------


@pytest.mark.parametrize(
    ("key", "modifiers", "expected"),
    [
        (Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier, "**Title**"),
        (Qt.Key.Key_I, Qt.KeyboardModifier.ControlModifier, "*Title*"),
        (
            Qt.Key.Key_2,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
            "## Title",
        ),
        (
            Qt.Key.Key_8,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
            "- Title",
        ),
    ],
)
def test_formatting_shortcuts(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    key: Qt.Key,
    modifiers: Qt.KeyboardModifier,
    expected: str,
) -> None:
    page = shown_page(qtbot, connection)
    page.editor.setFocus()
    page.editor.setPlainText("Title")
    cursor = page.editor.textCursor()
    cursor.select(QTextCursor.SelectionType.Document)
    page.editor.setTextCursor(cursor)

    qtbot.keyClick(page.editor, key, modifiers)

    assert page.editor.markdown().strip() == expected


def test_ctrl_n_starts_a_new_block_and_ctrl_s_saves_it(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    save_text_block(connection, TextBlock(name="A", content="x"))
    page = shown_page(qtbot, connection)
    page.item_list.setFocus()

    qtbot.keyClick(page.item_list, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    assert page.editor_box.title() == "New text block"
    assert page.focusWidget() is page.name_edit

    page.name_edit.setText("B")
    page.editor.setPlainText("y")
    qtbot.keyClick(page.name_edit, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert sorted(block.name for block in list_text_blocks(connection)) == ["A", "B"]


def test_delete_key_deletes_from_the_list_but_not_the_editor(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_text_block(connection, TextBlock(name="A", content="text"))
    page = shown_page(qtbot, connection)
    confirm = mocker.patch(f"{PAGE_MODULE}.confirm_destructive", return_value=False)

    page.editor.setFocus()
    qtbot.keyClick(page.editor, Qt.Key.Key_Delete)
    confirm.assert_not_called()

    page.item_list.setFocus()
    qtbot.keyClick(page.item_list, Qt.Key.Key_Delete)
    confirm.assert_called_once()


def test_fields_are_labelled_and_mnemonics_unique(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)

    for field_name, label in page.field_labels.items():
        interface = QAccessible.queryAccessibleInterface(page.field_widgets[field_name])
        labels = [
            related.text(QAccessible.Text.Name)
            for related, _ in interface.relations(QAccessible.RelationFlag.Label)
        ]
        assert labels[0] == label.text().replace("&", "")

    texts = [
        "Text &blocks",
        *(label.text() for label in page.field_labels.values()),
        "St&yle",
        *(
            button.text()
            for button in (
                page.new_button,
                page.duplicate_button,
                page.delete_button,
                page.save_button,
                page.revert_button,
            )
        ),
    ]
    mnemonics = [text[text.index("&") + 1].lower() for text in texts]
    assert len(mnemonics) == len(set(mnemonics)), mnemonics


def test_formatting_buttons_are_named_and_reachable_by_tab(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)

    for button, name in (
        (page.bold_button, "Bold"),
        (page.italic_button, "Italic"),
        (page.bulleted_button, "Bulleted list"),
        (page.numbered_button, "Numbered list"),
    ):
        interface = QAccessible.queryAccessibleInterface(button)
        assert interface.text(QAccessible.Text.Name) == name
        assert interface.text(QAccessible.Text.Description).startswith("Shortcut: ")
        assert button.focusPolicy() & Qt.FocusPolicy.TabFocus


def test_tab_order_follows_the_screen(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    expected = [
        page.item_list,
        page.new_button,
        page.duplicate_button,
        page.delete_button,
        page.name_edit,
        page.style_combo,
        page.bold_button,
        page.italic_button,
        page.bulleted_button,
        page.numbered_button,
        page.editor,
        page.revert_button,
        page.save_button,
    ]

    chain = [expected[0]]
    widget = expected[0]
    while len(chain) < len(expected):
        widget = widget.nextInFocusChain()
        if widget.focusPolicy() & Qt.FocusPolicy.TabFocus:
            chain.append(widget)

    assert chain == expected
