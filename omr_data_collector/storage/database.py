from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Each entry upgrades the schema by one version; SQLite's user_version records how
# many have run. Append new migrations, never edit old ones: databases in the field
# have already run them.
MIGRATIONS: list[list[str]] = [
    [
        """
        CREATE TABLE organization (
            organization_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            paper_size TEXT NOT NULL,
            orientation TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """,
    ],
    [
        """
        CREATE TABLE text_block (
            text_block_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """,
        # Names are unique ignoring case, matching TextBlock.validation_errors.
        "CREATE UNIQUE INDEX text_block_name ON text_block (name COLLATE NOCASE)",
    ],
    [
        """
        CREATE TABLE question (
            question_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            prompt TEXT NOT NULL,
            example TEXT NOT NULL DEFAULT '',
            -- AnswerSpec.to_dict() as JSON: the same shape forms copy.
            answer TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """,
        "CREATE UNIQUE INDEX question_name ON question (name COLLATE NOCASE)",
    ],
    [
        """
        CREATE TABLE table_block (
            table_block_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            instructions TEXT NOT NULL DEFAULT '',
            row_count INTEGER NOT NULL,
            -- columns_to_list() as JSON: the same shape forms copy.
            columns TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """,
        "CREATE UNIQUE INDEX table_block_name ON table_block (name COLLATE NOCASE)",
    ],
]


def open_database(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the app database at ``path`` and bring it up to date."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate(connection)
    return connection


def migrate(connection: sqlite3.Connection) -> None:
    (current_version,) = connection.execute("PRAGMA user_version").fetchone()
    if current_version > len(MIGRATIONS):
        msg = (
            f"The database is from a newer version of the app (schema "
            f"{current_version}, this app knows {len(MIGRATIONS)})."
        )
        raise RuntimeError(msg)

    for version, statements in enumerate(
        MIGRATIONS[current_version:], start=current_version + 1
    ):
        # One transaction per migration, so a failure leaves the previous version.
        with connection:
            for statement in statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {version}")
