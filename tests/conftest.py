from __future__ import annotations

import os
from typing import TYPE_CHECKING, NoReturn

import pytest
from PySide6.QtWidgets import QMessageBox

from omr_data_collector.storage.database import open_database

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from pathlib import Path

    from pytest_mock import MockerFixture

# Lets Qt run without a display (CI, containers, SSH sessions). Set before pytest-qt
# creates the QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    database = open_database(tmp_path / "test.sqlite3")
    yield database
    database.close()


@pytest.fixture(autouse=True)
def fail_on_unexpected_dialogs(mocker: MockerFixture) -> None:
    """Make a message box no test asked for fail at once instead of hanging.

    Offscreen, a real modal dialog waits forever for a click. Tests that expect a
    dialog patch it themselves, which replaces these.
    """

    def unexpected(*args: object, **_kwargs: object) -> NoReturn:
        msg = f"Unexpected dialog: {args[1:3]}"
        raise AssertionError(msg)

    for name in ("question", "warning", "information", "critical"):
        mocker.patch.object(QMessageBox, name, side_effect=unexpected)
    mocker.patch.object(QMessageBox, "exec", side_effect=unexpected)
