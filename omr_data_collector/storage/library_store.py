"""The three block libraries (text blocks, questions, tables) taken together."""

from __future__ import annotations

from typing import TYPE_CHECKING

from omr_data_collector.constants import BLOCK_KINDS
from omr_data_collector.models.Form import kind_of
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TableBlock import TableBlock
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.storage.question_store import list_questions, save_question
from omr_data_collector.storage.table_block_store import (
    list_table_blocks,
    save_table_block,
)
from omr_data_collector.storage.text_block_store import (
    list_text_blocks,
    save_text_block,
)

if TYPE_CHECKING:
    import sqlite3

    from omr_data_collector.models.Form import BlockContent

# The kinds of block a form can copy from a library (sheet details have none).
LIBRARY_KINDS = (BLOCK_KINDS.TEXT, BLOCK_KINDS.QUESTION, BLOCK_KINDS.TABLE)


def list_libraries(connection: sqlite3.Connection) -> dict[str, list[BlockContent]]:
    """Every library's blocks, by kind, each sorted by name ignoring case."""
    return {
        BLOCK_KINDS.TEXT: list(list_text_blocks(connection)),
        BLOCK_KINDS.QUESTION: list(list_questions(connection)),
        BLOCK_KINDS.TABLE: list(list_table_blocks(connection)),
    }


def library_blocks(connection: sqlite3.Connection) -> list[BlockContent]:
    """Every block in every library."""
    return [block for blocks in list_libraries(connection).values() for block in blocks]


def save_library_block(connection: sqlite3.Connection, block: BlockContent) -> None:
    """Store a block in its own library, inserting or updating it by ID.

    Raises:
        sqlite3.IntegrityError: Another block of its kind already has its name.
        TypeError: ``block`` is sheet details, which have no library.
    """
    if isinstance(block, TextBlock):
        save_text_block(connection, block)
    elif isinstance(block, Question):
        save_question(connection, block)
    elif isinstance(block, TableBlock):
        save_table_block(connection, block)
    else:
        raise TypeError(kind_of(block))
