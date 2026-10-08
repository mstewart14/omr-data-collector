from __future__ import annotations

import sqlite3
from dataclasses import replace

import jsonschema
import pytest

from omr_data_collector.constants import (
    ANSWER_TYPES,
    PAGE_ORIENTATIONS,
    TABLE_BREAKS,
)
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.storage.form_store import (
    delete_form,
    is_printed,
    list_forms,
    load_form_version,
    mark_printed,
    save_form,
)

TITLE = TextBlock(name="Title", content="# Client intake\n")
VISIT = Question(
    name="first_visit",
    prompt="Is this your first visit?",
    answer=AnswerSpec(ANSWER_TYPES.YES_NO, choices=(Choice("Yes"), Choice("No"))),
).normalized()
LOG = TableBlock(
    name="Visit log",
    fill_page=True,
    columns=(
        Column("time", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=5)),
    ),
)


def intake(**changes: object) -> Form:
    form = Form(
        name="Intake",
        orientation=PAGE_ORIENTATIONS.LANDSCAPE,
        blocks=(
            FormBlock(TITLE, source_id=TITLE.text_block_id),
            FormBlock(VISIT, source_id=None, start_on_new_page=True),
            FormBlock(
                LOG, source_id=LOG.table_block_id, table_break=TABLE_BREAKS.NEW_PAGE
            ),
        ),
    ).normalized()
    return replace(form, **changes)


# --- Model ----------------------------------------------------------------------


def test_valid_form_has_no_errors() -> None:
    assert intake().validation_errors(set()) == {}


def test_name_and_a_block_are_required() -> None:
    form = Form(name=" ").normalized()

    assert form.validation_errors(set()) == {
        "name": "Enter a name for the form.",
        "blocks": "Add at least one block.",
    }


def test_form_names_are_unique_ignoring_case() -> None:
    assert intake().validation_errors({"INTAKE"}) == {
        "name": 'Another form is already called "Intake".'
    }


def test_a_blocks_own_errors_name_the_block() -> None:
    empty_text = FormBlock(TextBlock(name="Notes", content=" "))
    form = intake(blocks=(empty_text,))

    assert form.validation_errors(set()) == {
        "blocks": 'Block 1 (text "Notes"): Enter the text for the block.'
    }


def test_questions_on_a_form_need_distinct_names() -> None:
    again = FormBlock(replace(VISIT, prompt="Again?"))
    form = intake(blocks=(FormBlock(VISIT), FormBlock(TITLE), again))

    assert form.validation_errors(set()) == {
        "blocks": 'Blocks 1 and 3 are both questions called "first_visit"; '
        "rename one so their data can be told apart."
    }


def test_a_text_block_and_question_may_share_a_name() -> None:
    form = intake(
        blocks=(FormBlock(replace(TITLE, name="first_visit")), FormBlock(VISIT))
    )

    assert form.validation_errors(set()) == {}


def test_definition_round_trips() -> None:
    form = intake(version=3)

    assert (
        Form.from_definition(form.definition(), form_id=form.form_id, version=3) == form
    )


def test_definition_is_checked_on_load() -> None:
    definition = intake().definition()
    definition["blocks"][0]["kind"] = "IMAGE"

    with pytest.raises(jsonschema.ValidationError):
        Form.from_definition(definition, form_id="x" * 32, version=1)


# --- Versions -------------------------------------------------------------------


def test_first_save_is_version_one(connection: sqlite3.Connection) -> None:
    saved = save_form(connection, intake())

    assert saved.version == 1
    assert list_forms(connection) == [saved]


def test_unprinted_versions_are_updated_in_place(
    connection: sqlite3.Connection,
) -> None:
    first = save_form(connection, intake())

    second = save_form(connection, replace(first, name="Client intake"))

    assert second.version == 1
    assert list_forms(connection) == [second]


def test_changes_after_printing_make_a_new_version(
    connection: sqlite3.Connection,
) -> None:
    first = save_form(connection, intake())
    mark_printed(connection, first.form_id, 1)

    second = save_form(
        connection, replace(first, orientation=PAGE_ORIENTATIONS.PORTRAIT)
    )

    assert second.version == 2
    assert is_printed(connection, first.form_id, 1)
    assert not is_printed(connection, first.form_id, 2)
    # The printed version is kept exactly as it was, for scanning its sheets.
    assert load_form_version(connection, first.form_id, 1) == first
    assert list_forms(connection) == [second]


def test_marking_printed_twice_keeps_the_first_time(
    connection: sqlite3.Connection,
) -> None:
    form = save_form(connection, intake())
    mark_printed(connection, form.form_id, 1)
    (first_time,) = connection.execute("SELECT printed_at FROM form_version").fetchone()

    mark_printed(connection, form.form_id, 1)

    (second_time,) = connection.execute(
        "SELECT printed_at FROM form_version"
    ).fetchone()
    assert first_time == second_time


def test_unknown_versions_load_as_none(connection: sqlite3.Connection) -> None:
    form = save_form(connection, intake())

    assert load_form_version(connection, form.form_id, 9) is None


def test_database_rejects_duplicate_form_names(
    connection: sqlite3.Connection,
) -> None:
    save_form(connection, intake())

    with pytest.raises(sqlite3.IntegrityError):
        save_form(connection, Form(name="INTAKE", blocks=(FormBlock(TITLE),)))


def test_delete_removes_every_version(connection: sqlite3.Connection) -> None:
    form = save_form(connection, intake())
    mark_printed(connection, form.form_id, 1)
    save_form(connection, replace(form, name="Intake 2"))

    delete_form(connection, form.form_id)

    assert list_forms(connection) == []
    (count,) = connection.execute("SELECT COUNT(*) FROM form_version").fetchone()
    assert count == 0
