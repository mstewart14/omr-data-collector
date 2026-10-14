from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from omr_data_collector.models.Form import Form

if TYPE_CHECKING:
    import sqlite3

    from omr_data_collector.models.Form import BlockContent


def list_forms(connection: sqlite3.Connection) -> list[Form]:
    """Every form at its latest version, sorted by name ignoring case."""
    rows = connection.execute(
        "SELECT form.form_id, form_version.version, form_version.definition"
        " FROM form JOIN form_version ON form_version.form_id = form.form_id"
        " WHERE form_version.version = ("
        "   SELECT MAX(version) FROM form_version WHERE form_id = form.form_id)"
        " ORDER BY form.name COLLATE NOCASE"
    ).fetchall()
    return [
        Form.from_definition(
            json.loads(row["definition"]),
            form_id=row["form_id"],
            version=row["version"],
        )
        for row in rows
    ]


def load_form_version(
    connection: sqlite3.Connection, form_id: str, version: int
) -> Form | None:
    """One stored version, such as the one a scanned sheet's QR code names."""
    row = connection.execute(
        "SELECT definition FROM form_version WHERE form_id = ? AND version = ?",
        (form_id, version),
    ).fetchone()
    if row is None:
        return None
    return Form.from_definition(
        json.loads(row["definition"]), form_id=form_id, version=version
    )


def is_printed(connection: sqlite3.Connection, form_id: str, version: int) -> bool:
    row = connection.execute(
        "SELECT printed_at FROM form_version WHERE form_id = ? AND version = ?",
        (form_id, version),
    ).fetchone()
    return row is not None and row["printed_at"] is not None


def save_form(connection: sqlite3.Connection, form: Form) -> Form:
    """Store the form; returns it with the version it was stored as.

    The latest version is updated in place until it has been printed. After
    that, saving makes a new version, keeping the printed one as it was (wiki
    acceptance criteria: sheets already handed out can still be scanned).

    Raises:
        sqlite3.IntegrityError: Another form already has this name.
    """
    definition = json.dumps(form.definition())
    with connection:
        connection.execute(
            "INSERT INTO form (form_id, name) VALUES (?, ?)"
            " ON CONFLICT(form_id) DO UPDATE SET name = excluded.name,"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
            (form.form_id, form.name),
        )
        latest = connection.execute(
            "SELECT version, printed_at FROM form_version WHERE form_id = ?"
            " ORDER BY version DESC LIMIT 1",
            (form.form_id,),
        ).fetchone()
        if latest is not None and latest["printed_at"] is None:
            version = latest["version"]
            connection.execute(
                "UPDATE form_version SET definition = ? WHERE form_id = ? AND version = ?",
                (definition, form.form_id, version),
            )
        else:
            version = latest["version"] + 1 if latest is not None else 1
            connection.execute(
                "INSERT INTO form_version (form_id, version, definition) VALUES (?, ?, ?)",
                (form.form_id, version, definition),
            )
    return replace(form, version=version)


def forms_with_other_copies(
    connection: sqlite3.Connection, source_id: str, content: BlockContent
) -> list[Form]:
    """Forms, at their latest version, with a copy of a library block unlike ``content``.

    ``source_id`` is the library block's ID (``FormBlock.source_id``): these are
    the forms that saving it everywhere would change (wiki 50012).
    """
    return [
        form
        for form in list_forms(connection)
        if any(
            block.source_id == source_id and block.content != content
            for block in form.blocks
        )
    ]


def update_copies(
    connection: sqlite3.Connection, source_id: str, content: BlockContent
) -> list[tuple[Form, bool]]:
    """Put ``content`` in place of every form's copy of library block ``source_id``.

    Each changed form is saved as ``save_form`` does: in place, or as a new
    version when its latest has been printed, so sheets already printed still
    scan. Returns each form as saved, and whether it got a new version.
    """
    saved = []
    for form in forms_with_other_copies(connection, source_id, content):
        blocks = tuple(
            replace(block, content=content) if block.source_id == source_id else block
            for block in form.blocks
        )
        stored = save_form(connection, replace(form, blocks=blocks))
        saved.append((stored, stored.version != form.version))
    return saved


def mark_printed(
    connection: sqlite3.Connection,
    form_id: str,
    version: int,
    printed_layout: dict[str, Any] | None = None,
) -> None:
    """Record that a version has been printed (or saved as a PDF), freezing it.

    ``printed_layout`` (from ``omr_template.printed_layout``) is the OMR template
    of every page as printed; only the first printing's is kept, since every copy
    of the version must scan the same way.
    """
    with connection:
        connection.execute(
            "UPDATE form_version SET printed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),"
            " printed_layout = ?"
            " WHERE form_id = ? AND version = ? AND printed_at IS NULL",
            (
                json.dumps(printed_layout) if printed_layout is not None else None,
                form_id,
                version,
            ),
        )


def load_printed_layout(
    connection: sqlite3.Connection, form_id: str, version: int
) -> dict[str, Any] | None:
    """The page templates stored when the version was first printed, if any."""
    row = connection.execute(
        "SELECT printed_layout FROM form_version WHERE form_id = ? AND version = ?",
        (form_id, version),
    ).fetchone()
    if row is None or row["printed_layout"] is None:
        return None
    return json.loads(row["printed_layout"])


def delete_form(connection: sqlite3.Connection, form_id: str) -> None:
    """Delete the form and every version of it."""
    with connection:
        connection.execute("DELETE FROM form WHERE form_id = ?", (form_id,))
