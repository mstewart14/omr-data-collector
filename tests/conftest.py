from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import pytest
from PySide6.QtCore import QLocale, QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from omr_data_collector.i18n import available_languages, install_translators
from omr_data_collector.layout.form_layout import layout_form
from omr_data_collector.layout.frozen_layout import printed_layout
from omr_data_collector.models.Organization import Organization
from omr_data_collector.storage.database import open_database
from omr_data_collector.storage.form_store import mark_printed, save_form
from omr_data_collector.storage.organization_store import save_organization
from omr_data_collector.ui import app_font
from tests.sheets import intake_form

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator

    from pytest_mock import MockerFixture

    from omr_data_collector.layout.form_layout import FormLayout
    from omr_data_collector.models.Form import Form

# Lets Qt run without a display (CI, containers, SSH sessions). Set before pytest-qt
# creates the QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Offscreen Qt on Windows looks for fonts only in its own (empty) fonts folder.
# Without real fonts nothing can be bold or italic, and Qt's Markdown writer, which
# checks the font it actually found, silently drops ** and * from saved text.
if sys.platform == "win32":
    os.environ.setdefault(
        "QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
    )


@pytest.fixture(scope="session", autouse=True)
def english(qapp: QApplication) -> None:
    """The app's text as people see it: English, with its plural forms."""
    install_translators(qapp, QLocale(QLocale.Language.English))


@pytest.fixture(autouse=True)
def own_preferences(tmp_path: Path) -> None:
    """Keep each test's preferences (the language) out of the real ones."""
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "config")
    )


@pytest.fixture(autouse=True)
def own_font(qapp: QApplication, mocker: MockerFixture) -> Iterator[None]:
    """Keep the real desktop's font out of tests, and each test's font to itself.

    ``main()`` and Preferences > Text size change the whole app's font, which
    every later test would otherwise see.
    """
    font = qapp.font()
    mocker.patch.object(app_font, "desktop_font", return_value=None)
    mocker.patch.object(app_font, "_desktop", None)
    yield
    QApplication.setFont(font)


@pytest.fixture(params=["en", *available_languages()])
def language(request: pytest.FixtureRequest, qapp: QApplication) -> Iterator[str]:
    """Runs a test once in each language the app is translated into."""
    install_translators(qapp, QLocale(request.param))
    yield request.param
    install_translators(qapp, QLocale(QLocale.Language.English))


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


@pytest.fixture
def organization(connection: sqlite3.Connection) -> Organization:
    """A saved organization, so forms can be printed."""
    organization = Organization("Food Bank")
    save_organization(connection, organization)
    return organization


@pytest.fixture
def printed_form(
    connection: sqlite3.Connection, organization: Organization
) -> tuple[Form, FormLayout]:
    """The intake form (``tests.sheets``), saved and printed, with its layout."""
    form = save_form(connection, intake_form())
    layout = layout_form(form, organization.paper_size)
    mark_printed(connection, form.form_id, form.version, printed_layout(layout))
    return form, layout
