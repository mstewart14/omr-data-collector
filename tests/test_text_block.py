from __future__ import annotations

import sqlite3

import pytest

from omr_data_collector.constants import TEXT_BLOCK_NAME_MAX_LENGTH
from omr_data_collector.models.naming import copy_name
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.storage.text_block_store import (
    delete_text_block,
    list_text_blocks,
    save_text_block,
)

# --- Model ----------------------------------------------------------------------


def test_valid_block_has_no_errors() -> None:
    block = TextBlock(name="Instructions", content="Fill in one bubble per row.")

    assert block.validation_errors(set()) == {}


def test_name_and_content_are_required() -> None:
    block = TextBlock(name="", content="  \n")

    assert set(block.validation_errors(set())) == {"name", "content"}


def test_name_length_is_limited() -> None:
    block = TextBlock(name="x" * (TEXT_BLOCK_NAME_MAX_LENGTH + 1), content="Text")

    assert set(block.validation_errors(set())) == {"name"}


def test_names_must_be_unique_ignoring_case() -> None:
    block = TextBlock(name="Footer", content="Thanks")

    errors = block.validation_errors({"FOOTER"})

    assert errors == {"name": 'Another text block is already called "Footer".'}


def test_normalized_trims_the_name() -> None:
    assert TextBlock(name="  Footer ", content="x").normalized().name == "Footer"


@pytest.mark.parametrize(
    ("taken", "expected"),
    [
        (set(), "Footer (copy)"),
        ({"footer (COPY)"}, "Footer (copy 2)"),
        ({"Footer (copy)", "Footer (copy 2)"}, "Footer (copy 3)"),
    ],
)
def test_copy_names_never_clash(taken: set[str], expected: str) -> None:
    assert copy_name("Footer", taken) == expected


# --- Storage --------------------------------------------------------------------


def test_blocks_list_sorted_by_name_ignoring_case(
    connection: sqlite3.Connection,
) -> None:
    for name in ("footer", "Title", "Instructions"):
        save_text_block(connection, TextBlock(name=name, content="x"))

    assert [block.name for block in list_text_blocks(connection)] == [
        "footer",
        "Instructions",
        "Title",
    ]


def test_saved_block_loads_back_unchanged(connection: sqlite3.Connection) -> None:
    block = TextBlock(name="Title", content="# Intake form\n\nOne per visit.\n")

    save_text_block(connection, block)

    assert list_text_blocks(connection) == [block]


def test_saving_again_updates_in_place(connection: sqlite3.Connection) -> None:
    block = TextBlock(name="Title", content="Old")
    save_text_block(connection, block)

    updated = TextBlock(
        name="Heading", content="New", text_block_id=block.text_block_id
    )
    save_text_block(connection, updated)

    assert list_text_blocks(connection) == [updated]


def test_database_rejects_duplicate_names_ignoring_case(
    connection: sqlite3.Connection,
) -> None:
    save_text_block(connection, TextBlock(name="Footer", content="x"))

    with pytest.raises(sqlite3.IntegrityError):
        save_text_block(connection, TextBlock(name="FOOTER", content="y"))


def test_delete_removes_only_that_block(connection: sqlite3.Connection) -> None:
    keep, doomed = (
        TextBlock(name="Keep", content="x"),
        TextBlock(name="Go", content="y"),
    )
    save_text_block(connection, keep)
    save_text_block(connection, doomed)

    delete_text_block(connection, doomed.text_block_id)

    assert list_text_blocks(connection) == [keep]
