from __future__ import annotations

import json
from typing import TYPE_CHECKING

from omr_data_collector.models.TableBlock import (
    TableBlock,
    columns_from_list,
    columns_to_list,
)

if TYPE_CHECKING:
    import sqlite3


def list_table_blocks(connection: sqlite3.Connection) -> list[TableBlock]:
    """Every saved table, sorted by name ignoring case."""
    rows = connection.execute(
        "SELECT table_block_id, name, instructions, row_count, columns"
        " FROM table_block ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [
        TableBlock(
            table_block_id=row["table_block_id"],
            name=row["name"],
            instructions=row["instructions"],
            rows=row["row_count"],
            columns=columns_from_list(json.loads(row["columns"])),
        )
        for row in rows
    ]


def save_table_block(connection: sqlite3.Connection, table: TableBlock) -> None:
    """Insert the table, or update it if its ID is already stored.

    Raises:
        sqlite3.IntegrityError: Another table already has this name.
    """
    with connection:
        connection.execute(
            "INSERT INTO table_block"
            " (table_block_id, name, instructions, row_count, columns)"
            " VALUES (:table_block_id, :name, :instructions, :row_count, :columns)"
            " ON CONFLICT(table_block_id) DO UPDATE SET"
            " name = excluded.name, instructions = excluded.instructions,"
            " row_count = excluded.row_count, columns = excluded.columns,"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
            {
                "table_block_id": table.table_block_id,
                "name": table.name,
                "instructions": table.instructions,
                "row_count": table.rows,
                "columns": json.dumps(columns_to_list(table.columns)),
            },
        )


def delete_table_block(connection: sqlite3.Connection, table_block_id: str) -> None:
    with connection:
        connection.execute(
            "DELETE FROM table_block WHERE table_block_id = ?", (table_block_id,)
        )
