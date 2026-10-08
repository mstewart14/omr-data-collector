from __future__ import annotations

from typing import TYPE_CHECKING

from omr_data_collector.models.TextBlock import TextBlock

if TYPE_CHECKING:
    import sqlite3


def list_text_blocks(connection: sqlite3.Connection) -> list[TextBlock]:
    """Every saved text block, sorted by name ignoring case."""
    rows = connection.execute(
        "SELECT text_block_id, name, content FROM text_block"
        " ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [TextBlock(**dict(row)) for row in rows]


def save_text_block(connection: sqlite3.Connection, text_block: TextBlock) -> None:
    """Insert the block, or update it if its ID is already stored.

    Raises:
        sqlite3.IntegrityError: Another block already has this name (ignoring case).
    """
    with connection:
        connection.execute(
            "INSERT INTO text_block (text_block_id, name, content)"
            " VALUES (:text_block_id, :name, :content)"
            " ON CONFLICT(text_block_id) DO UPDATE SET"
            " name = excluded.name, content = excluded.content,"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
            {
                "text_block_id": text_block.text_block_id,
                "name": text_block.name,
                "content": text_block.content,
            },
        )


def delete_text_block(connection: sqlite3.Connection, text_block_id: str) -> None:
    with connection:
        connection.execute(
            "DELETE FROM text_block WHERE text_block_id = ?", (text_block_id,)
        )
