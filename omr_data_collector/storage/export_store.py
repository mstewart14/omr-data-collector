"""The names a form's data is exported under, where they differ from the defaults."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from omr_data_collector.export.data_export import ExportNames

if TYPE_CHECKING:
    import sqlite3


def load_export_names(connection: sqlite3.Connection, form_id: str) -> ExportNames:
    row = connection.execute(
        "SELECT names FROM export_names WHERE form_id = ?", (form_id,)
    ).fetchone()
    return ExportNames.from_dict(json.loads(row["names"])) if row else ExportNames()


def save_export_names(
    connection: sqlite3.Connection, form_id: str, names: ExportNames
) -> None:
    with connection:
        connection.execute(
            "INSERT INTO export_names (form_id, names) VALUES (?, ?)"
            " ON CONFLICT(form_id) DO UPDATE SET names = excluded.names",
            (form_id, json.dumps(names.to_dict())),
        )
