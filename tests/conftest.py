from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from omr_data_collector.storage.database import open_database

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from pathlib import Path

# Lets Qt run without a display (CI, containers, SSH sessions). Set before pytest-qt
# creates the QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    database = open_database(tmp_path / "test.sqlite3")
    yield database
    database.close()
