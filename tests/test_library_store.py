"""The block libraries taken together, and the organization's paper size."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from omr_data_collector.constants import BLOCK_KINDS, PAPER_SIZES
from omr_data_collector.models.Organization import Organization, paper_size_of
from omr_data_collector.models.Question import Question
from omr_data_collector.models.SheetDetails import SheetDetails
from omr_data_collector.models.TableBlock import TableBlock
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.storage.library_store import (
    library_blocks,
    list_libraries,
    save_library_block,
)

if TYPE_CHECKING:
    import sqlite3


def test_each_block_is_stored_in_its_own_library(
    connection: sqlite3.Connection,
) -> None:
    text = TextBlock("Welcome", "Hello.")
    question = Question("visit", "First visit?")
    table = TableBlock("Log")

    for block in (table, question, text):
        save_library_block(connection, block)

    libraries = list_libraries(connection)
    assert [block.name for block in libraries[BLOCK_KINDS.TEXT]] == ["Welcome"]
    assert [block.name for block in libraries[BLOCK_KINDS.QUESTION]] == ["visit"]
    assert [block.name for block in libraries[BLOCK_KINDS.TABLE]] == ["Log"]
    assert len(library_blocks(connection)) == 3


def test_sheet_details_have_no_library(connection: sqlite3.Connection) -> None:
    with pytest.raises(TypeError):
        save_library_block(connection, SheetDetails(name="Sheet details"))


def test_paper_size_defaults_to_letter_before_an_organization() -> None:
    assert paper_size_of(None) == PAPER_SIZES.LETTER
    assert paper_size_of(Organization("Food Bank", paper_size=PAPER_SIZES.A4)) == (
        PAPER_SIZES.A4
    )
