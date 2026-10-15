"""Moving a form between computers: File > Export form and Import form."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from omr_data_collector.constants import PAPER_SIZES
from omr_data_collector.engine.scanning import scan_sheet
from omr_data_collector.layout.form_layout import layout_form
from omr_data_collector.layout.omr_template import printed_layout
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.Organization import Organization
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.storage.database import open_database
from omr_data_collector.storage.form_store import (
    list_forms,
    load_form_version,
    load_printed_layout,
    mark_printed,
    save_form,
)
from omr_data_collector.storage.form_transfer import (
    FILE_SUFFIX,
    FormFileError,
    ImportResult,
    apply_import,
    form_file,
    plan_import,
    read_form_file,
    stored_versions,
    write_form_file,
)
from omr_data_collector.storage.organization_store import save_organization
from omr_data_collector.storage.text_block_store import (
    list_text_blocks,
    save_text_block,
)
from omr_data_collector.ui.FormsPage import AddLibrary, FormsPage
from tests.sheets import Sheet, intake_form

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from pathlib import Path

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

    from omr_data_collector.layout.form_layout import FormLayout

PAGE_MODULE = "omr_data_collector.ui.FormsPage"
LETTER = PAPER_SIZES.LETTER
WELCOME = TextBlock("Welcome", "Thanks for coming.")


@pytest.fixture
def other(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """The other computer's database, with its own organization."""
    database = open_database(tmp_path / "other" / "app.sqlite3")
    save_organization(database, Organization("Second Site"))
    yield database
    database.close()


def print_version(connection: sqlite3.Connection, form: Form) -> None:
    layout = layout_form(form, LETTER)
    mark_printed(connection, form.form_id, form.version, printed_layout(layout))


def carry(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    form_id: str,
    tmp_path: Path,
    **choices: bool,
) -> ImportResult:
    """Export from ``source`` through a file and import into ``target``."""
    path = tmp_path / f"carried{FILE_SUFFIX}"
    with_library = choices.pop("with_library", True)
    write_form_file(path, form_file(source, form_id, with_library=with_library))
    plan = plan_import(target, read_form_file(path))
    assert not plan.problem
    return apply_import(target, plan, **choices)


# --- Storage ---------------------------------------------------------------------


def test_sheets_printed_on_one_computer_are_read_on_the_other(
    connection: sqlite3.Connection,
    other: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    form, layout = printed_form
    sheet = Sheet(form, organization, layout)
    sheet.fill_question(1, 0, 3)
    photo = sheet.photograph(tmp_path / "photo.jpg")

    carry(connection, other, form.form_id, tmp_path)

    assert load_form_version(other, form.form_id, 1) == load_form_version(
        connection, form.form_id, 1
    )
    assert load_printed_layout(other, form.form_id, 1) == load_printed_layout(
        connection, form.form_id, 1
    )
    page = scan_sheet(other, photo, LETTER)
    assert page.identity.form_id == form.form_id
    answers = {
        (answer.block_index, answer.table_row, answer.column): answer.values
        for answer in page.answers
    }
    assert answers[1, None, None] == ("food", "other")


def test_every_version_travels_and_only_the_latest_stays_unprinted(
    connection: sqlite3.Connection, other: sqlite3.Connection, tmp_path: Path
) -> None:
    form = save_form(connection, intake_form())
    print_version(connection, form)
    draft = save_form(connection, replace(form, name="Intake 2"))

    result = carry(connection, other, form.form_id, tmp_path)

    assert stored_versions(other, form.form_id) == stored_versions(
        connection, form.form_id
    )
    assert [stored.name for stored in list_forms(other)] == ["Intake 2"]
    assert result.added_versions == (1,)
    assert draft.version == 2


def test_the_library_blocks_go_only_when_asked(
    connection: sqlite3.Connection, other: sqlite3.Connection, tmp_path: Path
) -> None:
    save_text_block(connection, WELCOME)
    form = save_form(
        connection,
        replace(
            intake_form(),
            blocks=(FormBlock(WELCOME, source_id=WELCOME.text_block_id),),
        ),
    )

    assert form_file(connection, form.form_id, with_library=False).library == ()
    assert form_file(connection, form.form_id).library == (WELCOME,)

    carry(connection, other, form.form_id, tmp_path, with_library=False)
    assert list_text_blocks(other) == []
    carry(connection, other, form.form_id, tmp_path, add_blocks=False)
    assert list_text_blocks(other) == []
    carry(connection, other, form.form_id, tmp_path)
    assert list_text_blocks(other) == [WELCOME]


def test_a_library_block_here_is_replaced_only_when_asked(
    connection: sqlite3.Connection, other: sqlite3.Connection
) -> None:
    save_text_block(connection, WELCOME)
    save_text_block(other, replace(WELCOME, content="Changed here."))
    form = save_form(
        connection,
        replace(
            intake_form(),
            blocks=(FormBlock(WELCOME, source_id=WELCOME.text_block_id),),
        ),
    )
    exported = form_file(connection, form.form_id)

    plan = plan_import(other, exported)

    assert [block.name for block in plan.changed_blocks] == ["Welcome"]
    apply_import(other, plan)
    assert list_text_blocks(other)[0].content == "Changed here."
    apply_import(other, plan, replace_blocks=True)
    assert list_text_blocks(other) == [WELCOME]


def test_a_library_block_whose_name_is_taken_is_renamed(
    connection: sqlite3.Connection, other: sqlite3.Connection, tmp_path: Path
) -> None:
    save_text_block(connection, WELCOME)
    save_text_block(other, TextBlock("welcome", "Another block."))
    form = save_form(
        connection,
        replace(
            intake_form(),
            blocks=(FormBlock(WELCOME, source_id=WELCOME.text_block_id),),
        ),
    )

    result = carry(connection, other, form.form_id, tmp_path)

    assert result.renamed_blocks == (("Welcome", "Welcome (imported)"),)
    assert sorted(block.name for block in list_text_blocks(other)) == [
        "Welcome (imported)",
        "welcome",
    ]


def test_importing_again_changes_nothing(
    connection: sqlite3.Connection, other: sqlite3.Connection, tmp_path: Path
) -> None:
    form = save_form(connection, intake_form())
    print_version(connection, form)
    carry(connection, other, form.form_id, tmp_path)

    result = carry(connection, other, form.form_id, tmp_path)

    assert not result.changed_anything


def test_changes_on_both_computers_ask_which_become_the_latest(
    connection: sqlite3.Connection, other: sqlite3.Connection, tmp_path: Path
) -> None:
    form = save_form(connection, intake_form())
    print_version(connection, form)
    carry(connection, other, form.form_id, tmp_path)
    # Here: version 2 printed, then a draft of version 3.
    second = save_form(connection, replace(form, name="Intake printed"))
    print_version(connection, second)
    save_form(connection, replace(second, name="Intake here"))
    # There: a draft of version 2, which version 2 printed here overtakes.
    save_form(other, replace(form, name="Intake there"))

    path = tmp_path / f"a{FILE_SUFFIX}"
    write_form_file(path, form_file(connection, form.form_id))
    plan = plan_import(other, read_form_file(path))
    assert plan.choose_latest

    apply_import(other, plan, keep_local=True)
    versions = stored_versions(other, form.form_id)
    assert [version.version for version in versions] == [1, 2, 3]
    assert versions[1].definition["name"] == "Intake printed"
    assert versions[2].definition["name"] == "Intake there"
    assert not versions[2].printed

    apply_import(other, plan_import(other, read_form_file(path)), keep_local=False)
    assert list_forms(other)[0].name == "Intake here"


def test_a_draft_only_one_side_has_is_kept_without_asking(
    connection: sqlite3.Connection, other: sqlite3.Connection, tmp_path: Path
) -> None:
    form = save_form(connection, intake_form())
    print_version(connection, form)
    carry(connection, other, form.form_id, tmp_path)
    save_form(other, replace(form, name="Intake there"))

    path = tmp_path / f"a{FILE_SUFFIX}"
    write_form_file(path, form_file(connection, form.form_id))
    plan = plan_import(other, read_form_file(path))

    assert not plan.choose_latest
    apply_import(other, plan)
    assert list_forms(other)[0].name == "Intake there"


def test_a_version_printed_differently_on_each_computer_is_refused(
    connection: sqlite3.Connection, other: sqlite3.Connection, tmp_path: Path
) -> None:
    form = save_form(connection, intake_form())
    print_version(connection, form)
    carry(connection, other, form.form_id, tmp_path)
    for database, name in ((connection, "Intake here"), (other, "Intake there")):
        print_version(database, save_form(database, replace(form, name=name)))

    plan = plan_import(other, form_file(connection, form.form_id))

    assert "Version 2 of this form was printed on both computers" in plan.problem
    with pytest.raises(ValueError, match="Version 2"):
        apply_import(other, plan)


def test_a_different_form_with_the_same_name_is_refused(
    connection: sqlite3.Connection, other: sqlite3.Connection
) -> None:
    form = save_form(connection, intake_form())
    save_form(other, intake_form())

    plan = plan_import(other, form_file(connection, form.form_id))

    assert plan.problem.startswith('Another form here is already called "Intake"')


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ("not json", "couldn't be read"),
        (json.dumps({"format": "something else"}), "isn't a form exported"),
        (
            json.dumps({"format": "omr-data-collector-form", "formatVersion": 99}),
            "newer version",
        ),
        (
            json.dumps(
                {
                    "format": "omr-data-collector-form",
                    "formatVersion": 1,
                    "formId": "0" * 32,
                    "versions": [{"version": 1, "definition": {"name": 3}}],
                    "library": [],
                }
            ),
            "damaged",
        ),
    ],
)
def test_a_file_that_isnt_an_exported_form_is_refused(
    tmp_path: Path, content: str, problem: str
) -> None:
    path = tmp_path / f"bad{FILE_SUFFIX}"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(FormFileError, match=problem):
        read_form_file(path)


# --- The editor's commands -------------------------------------------------------


@pytest.fixture
def page(qtbot: QtBot, connection: sqlite3.Connection) -> FormsPage:
    save_text_block(connection, WELCOME)
    form = save_form(
        connection,
        replace(
            intake_form(),
            blocks=(
                *intake_form().blocks,
                FormBlock(WELCOME, source_id=WELCOME.text_block_id),
            ),
        ),
    )
    editor = FormsPage(connection)
    qtbot.addWidget(editor)
    editor.open_item(form.form_id)
    return editor


def statuses_of(page: FormsPage) -> list[str]:
    statuses: list[str] = []
    page.status_message.connect(statuses.append)
    return statuses


def test_export_form_asks_about_library_blocks_and_writes_the_file(
    page: FormsPage, mocker: MockerFixture, tmp_path: Path
) -> None:
    path = tmp_path / f"Intake{FILE_SUFFIX}"
    ask = mocker.patch(f"{PAGE_MODULE}.ask_include_library", return_value=False)
    choose = mocker.patch(f"{PAGE_MODULE}.choose_form_file_path", return_value=path)
    statuses = statuses_of(page)

    page.export_form()

    assert ask.call_args.args[1] == 1
    assert choose.call_args.args[1] == f"Intake{FILE_SUFFIX}"
    exported = read_form_file(path)
    assert exported.library == ()
    assert statuses[-1] == f'Exported the form "Intake", 1 version, to {path}.'


def test_export_form_cancelled_writes_nothing(
    page: FormsPage, mocker: MockerFixture
) -> None:
    mocker.patch(f"{PAGE_MODULE}.ask_include_library", return_value=None)
    choose = mocker.patch(f"{PAGE_MODULE}.choose_form_file_path")

    page.export_form()

    choose.assert_not_called()


def test_import_form_opens_the_imported_form(  # noqa: PLR0913 (fixtures)
    page: FormsPage,
    connection: sqlite3.Connection,
    other: sqlite3.Connection,
    mocker: MockerFixture,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    form = page.items()[0]
    path = tmp_path / f"Intake{FILE_SUFFIX}"
    write_form_file(path, form_file(connection, form.form_id))
    there = FormsPage(other)
    qtbot.addWidget(there)
    mocker.patch(f"{PAGE_MODULE}.choose_form_file_to_import", return_value=path)
    ask = mocker.patch(
        f"{PAGE_MODULE}.ask_add_library", return_value=AddLibrary.ADD_NEW
    )
    statuses = statuses_of(there)

    there.import_form()

    assert ask.call_args.args[1:] == (1, [])
    assert there.name_edit.text() == "Intake"
    assert list_text_blocks(other) == [WELCOME]
    assert statuses[-1] == (
        'Imported the form "Intake" with 1 version. Added 1 library block.'
    )


def test_import_form_explains_a_bad_file(
    page: FormsPage, mocker: MockerFixture, tmp_path: Path
) -> None:
    path = tmp_path / f"bad{FILE_SUFFIX}"
    path.write_text("{}", encoding="utf-8")
    mocker.patch(f"{PAGE_MODULE}.choose_form_file_to_import", return_value=path)
    warning = mocker.patch(f"{PAGE_MODULE}.QMessageBox.warning")

    page.import_form()

    assert "isn't a form exported" in warning.call_args.args[2]
