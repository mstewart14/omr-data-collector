from __future__ import annotations

import sqlite3

import jsonschema
import pytest

from omr_data_collector.constants import (
    ANSWER_TYPES,
    MAX_TABLE_ROWS,
    WRITTEN_DATA_TYPES,
)
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.TableBlock import (
    Column,
    TableBlock,
    columns_from_list,
    columns_to_list,
)
from omr_data_collector.storage.table_block_store import (
    delete_table_block,
    list_table_blocks,
    save_table_block,
)

TIME = Column(
    "time",
    "HH:MM",
    AnswerSpec(
        ANSWER_TYPES.WRITTEN,
        data_type=WRITTEN_DATA_TYPES.DATE_TIME,
        date_time_format="HH:MM",
    ),
)
FIRST_VISIT = Column(
    "first_visit",
    answer=AnswerSpec(
        ANSWER_TYPES.YES_NO, choices=(Choice("Y", "yes"), Choice("N", "no"))
    ),
)
VISIT_LOG = TableBlock(
    name="Visit log",
    instructions="One row per visit.\n",
    rows=25,
    columns=(TIME, FIRST_VISIT),
)


def test_valid_table_has_no_errors() -> None:
    assert VISIT_LOG.normalized().validation_errors(set()) == {}


def test_name_and_a_column_are_required() -> None:
    table = TableBlock(name=" ").normalized()

    assert table.validation_errors(set()) == {
        "name": "Enter a name for the table.",
        "columns": "Add at least one column.",
    }


def test_table_names_are_unique_ignoring_case() -> None:
    errors = VISIT_LOG.validation_errors({"VISIT LOG"})

    assert errors == {"name": 'Another table is already called "Visit log".'}


@pytest.mark.parametrize("rows", [0, MAX_TABLE_ROWS + 1])
def test_row_count_is_limited(rows: int) -> None:
    table = TableBlock(name="t", rows=rows, columns=(TIME,))

    assert set(table.validation_errors(set())) == {"rows"}


def test_column_names_are_unique_within_a_table() -> None:
    table = TableBlock(name="t", columns=(TIME, Column("TIME", answer=TIME.answer)))

    assert table.validation_errors(set()) == {
        "columns": 'Column 1 ("time"): This table already has a column called "time".'
    }


def test_identical_columns_still_count_as_two() -> None:
    table = TableBlock(name="t", columns=(TIME, TIME))

    assert "columns" in table.validation_errors(set())


def test_a_columns_answer_errors_name_the_column() -> None:
    broken = Column("services", answer=AnswerSpec(ANSWER_TYPES.ONE_CHOICE, choices=()))
    table = TableBlock(name="t", columns=(TIME, broken))

    assert table.validation_errors(set()) == {
        "columns": 'Column 2 ("services"): Add at least 3 choices.'
    }


def test_column_needs_a_name() -> None:
    assert set(Column("").normalized().validation_errors(set())) == {"name"}


def test_columns_json_round_trips() -> None:
    columns = (TIME.normalized(), FIRST_VISIT.normalized())

    assert columns_from_list(columns_to_list(columns)) == columns


def test_columns_json_is_checked_on_load() -> None:
    with pytest.raises(jsonschema.ValidationError):
        columns_from_list([{"name": "x", "answer": {"answerType": "YES_NO"}}])


def test_saved_table_loads_back_unchanged(connection: sqlite3.Connection) -> None:
    table = VISIT_LOG.normalized()

    save_table_block(connection, table)

    assert list_table_blocks(connection) == [table]


def test_database_rejects_duplicate_table_names(
    connection: sqlite3.Connection,
) -> None:
    save_table_block(connection, VISIT_LOG)

    with pytest.raises(sqlite3.IntegrityError):
        save_table_block(connection, TableBlock(name="visit LOG", columns=(TIME,)))


def test_delete(connection: sqlite3.Connection) -> None:
    save_table_block(connection, VISIT_LOG)

    delete_table_block(connection, VISIT_LOG.table_block_id)

    assert list_table_blocks(connection) == []
