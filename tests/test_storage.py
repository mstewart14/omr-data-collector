from __future__ import annotations

import dataclasses
import os
import sqlite3
import stat
from typing import TYPE_CHECKING

import pytest

from omr_data_collector.constants import PAGE_ORIENTATIONS, PAPER_SIZES
from omr_data_collector.models.Organization import Organization
from omr_data_collector.storage import database
from omr_data_collector.storage.database import MIGRATIONS, migrate, open_database
from omr_data_collector.storage.organization_store import (
    load_organization,
    save_organization,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_new_database_is_migrated_to_the_latest_version(
    connection: sqlite3.Connection,
) -> None:
    (version,) = connection.execute("PRAGMA user_version").fetchone()

    assert version == len(MIGRATIONS)


def test_reopening_a_database_keeps_its_data(tmp_path: Path) -> None:
    path = tmp_path / "data" / "app.sqlite3"
    organization = Organization(name="Food Bank")
    first = open_database(path)
    save_organization(first, organization)
    first.close()

    second = open_database(path)
    try:
        assert load_organization(second) == organization
    finally:
        second.close()


def test_refuses_a_database_from_a_newer_app(tmp_path: Path) -> None:
    path = tmp_path / "app.sqlite3"
    newer = sqlite3.connect(path)
    newer.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
    newer.close()

    with pytest.raises(RuntimeError, match="newer version"):
        open_database(path)


def test_a_migration_that_fails_halfway_leaves_nothing_done(
    connection: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    halfway = [
        "CREATE TABLE half (x TEXT)",
        "ALTER TABLE organization ADD COLUMN half TEXT",
        "NOT SQL",
    ]
    monkeypatch.setattr(database, "MIGRATIONS", [*MIGRATIONS, halfway])

    with pytest.raises(sqlite3.OperationalError):
        migrate(connection)

    (version,) = connection.execute("PRAGMA user_version").fetchone()
    assert version == len(MIGRATIONS)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert "half" not in tables
    columns = {row[1] for row in connection.execute("PRAGMA table_info(organization)")}
    assert "half" not in columns
    # Fixed, it runs again from the start.
    monkeypatch.setattr(database, "MIGRATIONS", [*MIGRATIONS, halfway[:2]])
    migrate(connection)
    (version,) = connection.execute("PRAGMA user_version").fetchone()
    assert version == len(MIGRATIONS) + 1


@pytest.mark.skipif(os.name == "nt", reason="Windows keeps app data per user")
def test_the_data_folder_is_open_to_this_account_only(tmp_path: Path) -> None:
    folder = tmp_path / "data"
    folder.mkdir(mode=0o755)

    open_database(folder / "app.sqlite3").close()

    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_no_organization_before_one_is_saved(connection: sqlite3.Connection) -> None:
    assert load_organization(connection) is None


def test_saved_organization_loads_back_unchanged(
    connection: sqlite3.Connection,
) -> None:
    organization = Organization(
        name="Food Bank",
        phone="613-555-0123",
        address="1 Main St\nOttawa",
        url="https://example.org",
        email="info@example.org",
        paper_size=PAPER_SIZES.A4,
        orientation=PAGE_ORIENTATIONS.LANDSCAPE,
    )

    save_organization(connection, organization)

    assert load_organization(connection) == organization


def test_saving_again_updates_in_place_and_keeps_the_id(
    connection: sqlite3.Connection,
) -> None:
    organization = Organization(name="Food Bank")
    save_organization(connection, organization)

    renamed = dataclasses.replace(organization, name="Community Food Bank")
    save_organization(connection, renamed)

    assert load_organization(connection) == renamed
    (count,) = connection.execute("SELECT COUNT(*) FROM organization").fetchone()
    assert count == 1
