from __future__ import annotations

from typing import TYPE_CHECKING

from omr_data_collector.models.Organization import Organization

if TYPE_CHECKING:
    import sqlite3

# SQL here is built from these fixed column names only; every value goes through a
# query parameter, which is why the S608 (SQL injection) warnings are suppressed.
ORGANIZATION_COLUMNS = (
    "organization_id",
    "name",
    "phone",
    "address",
    "url",
    "email",
    "paper_size",
    "orientation",
)


def load_organization(connection: sqlite3.Connection) -> Organization | None:
    """Return this installation's organization, or None before one is entered.

    The stories describe one organization per installation ("my data"), so this
    returns the first one created. The table allows more, for when that changes.
    """
    row = connection.execute(
        f"SELECT {', '.join(ORGANIZATION_COLUMNS)} FROM organization"  # noqa: S608
        " ORDER BY created_at LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return Organization(**dict(row))


def save_organization(
    connection: sqlite3.Connection, organization: Organization
) -> None:
    """Insert the organization, or update it if its ID is already stored."""
    placeholders = ", ".join(f":{column}" for column in ORGANIZATION_COLUMNS)
    updates = ", ".join(
        f"{column} = excluded.{column}"
        for column in ORGANIZATION_COLUMNS
        if column != "organization_id"
    )
    with connection:
        connection.execute(
            f"INSERT INTO organization ({', '.join(ORGANIZATION_COLUMNS)})"  # noqa: S608
            f" VALUES ({placeholders})"
            f" ON CONFLICT(organization_id) DO UPDATE SET {updates},"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
            {column: getattr(organization, column) for column in ORGANIZATION_COLUMNS},
        )
