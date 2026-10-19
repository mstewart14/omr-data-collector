"""Saving a library block that forms have copies of (wiki 50011-50012)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.storage.form_store import (
    list_forms,
    load_form_version,
    mark_printed,
    save_form,
)
from omr_data_collector.storage.question_store import save_question
from omr_data_collector.storage.table_block_store import save_table_block
from omr_data_collector.storage.text_block_store import save_text_block
from omr_data_collector.ui.form_helpers import ChangeWhere
from omr_data_collector.ui.FormsPage import FormsPage
from omr_data_collector.ui.QuestionsPage import QuestionsPage
from omr_data_collector.ui.TableBlocksPage import TableBlocksPage
from omr_data_collector.ui.TextBlocksPage import TextBlocksPage

if TYPE_CHECKING:
    import sqlite3

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

ASK = "omr_data_collector.ui.LibraryPage.ask_where_to_change"


def stored_text_block(connection: sqlite3.Connection) -> TextBlock:
    block = TextBlock(name="welcome", content="Welcome.")
    save_text_block(connection, block)
    return block


def stored_question(connection: sqlite3.Connection) -> Question:
    question = Question("visit", "First visit?")
    save_question(connection, question)
    return question


def stored_table(connection: sqlite3.Connection) -> TableBlock:
    table = TableBlock("Log", rows=3, columns=(Column("handle"),))
    save_table_block(connection, table)
    return table


KINDS = {
    "text block": (TextBlocksPage, stored_text_block, "text_block_id"),
    "question": (QuestionsPage, stored_question, "question_id"),
    "table": (TableBlocksPage, stored_table, "table_block_id"),
}


@pytest.fixture(params=list(KINDS))
def library(
    request: pytest.FixtureRequest, qtbot: QtBot, connection: sqlite3.Connection
):
    """A library page with one saved block, open, and two forms using it.

    "Draft" hasn't been printed; "Printed" has.
    """
    page_type, store, id_name = KINDS[request.param]
    block = store(connection)
    block_id = getattr(block, id_name)
    for name in ("Draft", "Printed"):
        form = save_form(
            connection,
            Form(name=name, blocks=(FormBlock(content=block, source_id=block_id),)),
        )
        if name == "Printed":
            mark_printed(connection, form.form_id, form.version)
    page = page_type(connection)
    qtbot.addWidget(page)
    assert page.open_item(block_id)
    return page, block_id


def edit(page: TextBlocksPage | QuestionsPage | TableBlocksPage) -> None:
    fields = (
        page.table_fields.text_fields
        if isinstance(page, TableBlocksPage)
        else page.text_fields
    )
    fields.editor.setPlainText("Changed in the library.")


def copies(connection: sqlite3.Connection, block_id: str) -> dict[str, tuple[int, str]]:
    """Each form's name, its latest version, and its copy's text."""
    found = {}
    for form in list_forms(connection):
        (block,) = [b for b in form.blocks if b.source_id == block_id]
        content = block.content
        text = getattr(content, "content", None) or getattr(content, "prompt", None)
        text = text or getattr(content, "instructions", "")
        found[form.name] = (form.version, text.strip())
    return found


def test_saving_asks_whether_the_forms_change_too(
    library, mocker: MockerFixture
) -> None:
    page, _ = library
    edit(page)
    ask = mocker.patch(ASK, return_value=ChangeWhere.GOING_FORWARD)

    assert page.save()

    ask.assert_called_once()
    question = ask.call_args.args[1]
    assert "2 forms" in question
    assert '"Draft"' in question
    assert '"Printed"' in question


def test_going_forward_leaves_the_forms_as_they_were(
    library, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    page, block_id = library
    before = copies(connection, block_id)
    edit(page)
    mocker.patch(ASK, return_value=ChangeWhere.GOING_FORWARD)

    assert page.save()

    assert copies(connection, block_id) == before
    assert not page.has_unsaved_changes()


def test_everywhere_changes_the_copies_and_versions_printed_forms(
    library, connection: sqlite3.Connection, mocker: MockerFixture, qtbot: QtBot
) -> None:
    page, block_id = library
    edit(page)
    mocker.patch(ASK, return_value=ChangeWhere.EVERYWHERE)

    with qtbot.waitSignal(page.status_message) as status:
        assert page.save()

    changed = "Changed in the library."
    assert copies(connection, block_id) == {
        "Draft": (1, changed),  # Not printed: changed in place.
        "Printed": (2, changed),  # Printed: a new version...
    }
    # ...and the printed one kept as it was, so its sheets still scan.
    printed = next(form for form in list_forms(connection) if form.name == "Printed")
    old = load_form_version(connection, printed.form_id, 1)
    assert old is not None
    assert changed not in str(old.blocks[0].content)
    assert status.args is not None
    (message,) = status.args
    assert "Changed on 2 forms too." in message
    assert "1 had been printed and got a new version." in message


def test_cancelling_saves_nothing(
    library, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    page, block_id = library
    before = copies(connection, block_id)
    edit(page)
    mocker.patch(ASK, return_value=None)

    assert not page.save()

    assert page.has_unsaved_changes()
    assert copies(connection, block_id) == before
    assert "Changed in the library." not in str(page.list_items())


def test_nothing_is_asked_when_no_form_has_a_different_copy(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    block = stored_question(connection)
    page = QuestionsPage(connection)
    qtbot.addWidget(page)
    page.open_item(block.question_id)
    edit(page)
    ask = mocker.patch(ASK)

    assert page.save()

    ask.assert_not_called()


def test_the_open_form_shows_a_change_made_everywhere(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    block = stored_question(connection)
    form = save_form(
        connection,
        Form(
            name="Draft",
            blocks=(FormBlock(content=block, source_id=block.question_id),),
        ),
    )
    forms = FormsPage(connection)
    qtbot.addWidget(forms)
    forms.open_item(form.form_id)
    questions = QuestionsPage(connection)
    qtbot.addWidget(questions)
    questions.open_item(block.question_id)
    edit(questions)
    mocker.patch(ASK, return_value=ChangeWhere.EVERYWHERE)
    assert questions.save()

    forms.show()

    (copy,) = forms.items()[0].blocks
    assert "Changed in the library." in str(copy.content)
    assert forms._current == forms.items()[0]  # noqa: SLF001 (what the editor holds)
    assert not forms.has_unsaved_changes()
