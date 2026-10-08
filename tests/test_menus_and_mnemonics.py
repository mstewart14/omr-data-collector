from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING

import pytest
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QAbstractButton, QLabel, QMessageBox, QWidget

from omr_data_collector.constants import BLOCK_KINDS
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.storage.question_store import list_questions
from omr_data_collector.storage.text_block_store import save_text_block
from omr_data_collector.ui.BlockDialogs import BlockContentDialog, BlockPickerDialog
from omr_data_collector.ui.ColumnDialog import ColumnDialog
from omr_data_collector.ui.form_helpers import ask_new_or_keep_working
from omr_data_collector.ui.MainWindow import MENU_MNEMONICS, MainWindow

if TYPE_CHECKING:
    import sqlite3

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

MNEMONIC = re.compile(r"&([^&])")


def mnemonics_in(root: QWidget) -> list[str]:
    """Every Alt+letter on labels and buttons inside ``root``, hidden ones too."""
    letters = []
    for widget in root.findChildren(QWidget):
        if isinstance(widget, (QLabel, QAbstractButton)):
            match = MNEMONIC.search(widget.text().replace("&&", ""))
            if match:
                letters.append(match.group(1).lower())
    return letters


def mnemonics_of(texts: list[str]) -> list[str]:
    return [
        match.group(1).lower()
        for text in texts
        if (match := MNEMONIC.search(text.replace("&&", "")))
    ]


def native(key: QKeySequence.StandardKey) -> str:
    return QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)


def make_window(qtbot: QtBot, connection: sqlite3.Connection) -> MainWindow:
    window = MainWindow(connection)
    qtbot.addWidget(window)
    return window


def menu_texts(menu) -> list[str]:
    return [action.text() for action in menu.actions() if not action.isSeparator()]


# --- Mnemonics --------------------------------------------------------------------


def test_menu_letters_are_what_pages_avoid(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    window = make_window(qtbot, connection)

    titles = [
        menu.title()
        for menu in (
            window.file_menu,
            window.text_menu,
            window.question_menu,
            window.table_menu,
        )
    ]

    assert titles == ["&File", "&Text", "&Question", "T&able"]
    assert set(mnemonics_of(titles)) == MENU_MNEMONICS


@pytest.mark.parametrize("section", range(5))
def test_each_page_has_unique_mnemonics_clear_of_the_menus(
    qtbot: QtBot, connection: sqlite3.Connection, section: int
) -> None:
    window = make_window(qtbot, connection)
    title, page = window.pages[section]

    letters = mnemonics_in(page)

    assert letters, title
    assert len(letters) == len(set(letters)), (title, sorted(letters))
    assert not set(letters) & MENU_MNEMONICS, (title, set(letters) & MENU_MNEMONICS)


@pytest.mark.parametrize(
    "make_dialog",
    [
        lambda: ColumnDialog(None, None, set()),
        lambda: BlockContentDialog(None, BLOCK_KINDS.TEXT, None),
        lambda: BlockContentDialog(None, BLOCK_KINDS.QUESTION, None),
        lambda: BlockPickerDialog(None, "question", [], can_write_new=True),
    ],
    ids=["column", "text", "question", "picker"],
)
def test_each_dialog_has_unique_mnemonics(qtbot: QtBot, make_dialog) -> None:
    dialog = make_dialog()
    qtbot.addWidget(dialog)

    letters = mnemonics_in(dialog)

    assert len(letters) == len(set(letters)), sorted(letters)


# --- Menus ------------------------------------------------------------------------


def test_file_menu_holds_the_form_commands(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    window = make_window(qtbot, connection)

    assert menu_texts(window.file_menu) == [
        "&New form",
        "&Open form…",
        "&Save form",
        "&Revert form",
        "D&uplicate form",
        "&Delete form…",
        f"U&ndo form change\t{native(QKeySequence.StandardKey.Undo)}",
        f"Re&do form change\t{native(QKeySequence.StandardKey.Redo)}",
        "&Organization details…",
        "&Quit",
    ]
    assert menu_texts(window.question_menu)[0] == "&New question"
    assert menu_texts(window.table_menu)[0] == "&New table"
    assert menu_texts(window.text_menu)[0] == "&New text block"


def test_a_menu_command_opens_its_section_and_acts_there(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    save_text_block(connection, TextBlock(name="Footer", content="Thanks"))
    window = make_window(qtbot, connection)
    new_text = window.text_menu.actions()[0]

    new_text.trigger()

    assert window.stack.currentWidget() is window.text_blocks_page
    assert window.text_blocks_page.editor_box.title() == "New text block"


def test_menu_commands_are_enabled_like_the_pages_buttons(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    window = make_window(qtbot, connection)
    menu = window.question_menu

    menu.aboutToShow.emit()

    enabled = {action.text(): action.isEnabled() for action in menu.actions()}
    assert enabled == {
        "&New question": True,
        "&Save question": False,
        "&Revert question": False,
        "D&uplicate question": False,
        "&Delete question…": False,
    }


def test_organization_details_opens_the_organization_section(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    window = make_window(qtbot, connection)
    window.open_section(3)
    organization = next(
        action
        for action in window.file_menu.actions()
        if action.text() == "&Organization details…"
    )

    organization.trigger()

    assert window.stack.currentWidget() is window.organization_page


# --- Question: new or keep working ------------------------------------------------


def write_question(window: MainWindow) -> None:
    page = window.questions_page
    page.new_item()
    page.name_edit.setText("first_visit")
    page.text_fields.editor.setPlainText("Is this your first visit?")


@pytest.mark.parametrize(
    ("start_new", "editing"), [(True, "New question"), (False, 'Editing "first_visit"')]
)
def test_saving_a_question_offers_a_new_one(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    start_new: bool,  # noqa: FBT001
    editing: str,
) -> None:
    window = make_window(qtbot, connection)
    write_question(window)
    ask = mocker.patch(
        "omr_data_collector.ui.QuestionsPage.ask_new_or_keep_working",
        return_value=start_new,
    )

    window.questions_page.save_button.click()

    ask.assert_called_once_with(window.questions_page, "question", "first_visit")
    assert [question.name for question in list_questions(connection)] == ["first_visit"]
    assert window.questions_page.editor_box.title() == editing


def test_saving_a_question_on_the_way_to_something_else_does_not_ask(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    window = make_window(qtbot, connection)
    write_question(window)
    ask = mocker.patch("omr_data_collector.ui.QuestionsPage.ask_new_or_keep_working")

    assert window.questions_page.save()

    ask.assert_not_called()


def test_a_question_that_fails_to_save_does_not_ask(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    window = make_window(qtbot, connection)
    window.questions_page.name_edit.setText("no prompt")
    ask = mocker.patch("omr_data_collector.ui.QuestionsPage.ask_new_or_keep_working")

    window.questions_page.save_from_user()

    ask.assert_not_called()
    window.questions_page.revert()  # so closing the window doesn't ask about it


@pytest.mark.parametrize(
    ("clicked", "expected"), [("&New question", True), ("&Keep working", False)]
)
def test_new_or_keep_working_dialog(
    qtbot: QtBot,
    mocker: MockerFixture,
    clicked: str,
    expected: bool,  # noqa: FBT001
) -> None:
    def run(self: QMessageBox) -> int:
        # Stands in for the person: checks the safe default, then clicks.
        button = next(b for b in self.buttons() if b.text() == clicked)
        assert self.defaultButton().text() == "&Keep working"
        assert self.escapeButton() is next(
            b for b in self.buttons() if b.text() == "&Keep working"
        )
        mocker.patch.object(self, "clickedButton", return_value=button)
        return 0

    mocker.patch.object(QMessageBox, "exec", run)
    parent = QWidget()
    qtbot.addWidget(parent)

    assert ask_new_or_keep_working(parent, "question", "first_visit") is expected


def test_question_dialog_text_names_the_question(
    qtbot: QtBot, mocker: MockerFixture
) -> None:
    seen: dict[str, str] = {}

    def run(self: QMessageBox) -> int:
        seen["text"] = self.text()
        seen["title"] = self.windowTitle()
        return 0

    mocker.patch.object(QMessageBox, "exec", run)
    parent = QWidget()
    qtbot.addWidget(parent)

    ask_new_or_keep_working(parent, "question", "first_visit")

    assert seen["text"] == (
        'Question "first_visit" saved. Start a new question, or keep working on '
        "this one?"
    )
    # macOS message boxes have no title bar, so Qt drops the title there; the
    # text above says the same thing.
    if sys.platform != "darwin":
        assert seen["title"] == "Question saved"
