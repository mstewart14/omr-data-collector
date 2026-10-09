"""Exporting checked sheets as CSV files and JSON."""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt

from omr_data_collector.constants import ANSWER_TYPES, CAPTURE_STATUSES
from omr_data_collector.export.data_export import (
    SHEET_COLUMNS,
    collect,
    saved_sheet_counts,
    write_csv,
    write_json,
)
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Capture import CapturedAnswer
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.Question import Question
from omr_data_collector.models.SheetDetails import SheetDetails
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.storage.capture_store import add_capture, save_capture
from omr_data_collector.storage.form_store import mark_printed, save_form
from omr_data_collector.ui.CapturePage import CapturePage
from omr_data_collector.ui.ExportDialog import CSV_FORMAT, JSON_FORMAT, ExportDialog

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.usefixtures("qapp")

DETAILS = SheetDetails(
    name="Sheet details",
    fields=(
        Column("Date", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=10)),
        Column(
            "Shift",
            answer=AnswerSpec(
                ANSWER_TYPES.ONE_CHOICE,
                choices=(
                    Choice("Day", "day"),
                    Choice("Evening", "evening"),
                    Choice("Night", "night"),
                ),
            ),
        ),
    ),
)
SERVICES = Question(
    "services",
    "Services?",
    answer=AnswerSpec(
        ANSWER_TYPES.MANY_CHOICES,
        choices=(
            Choice("Food", "food"),
            Choice("Clothing", "clothing"),
            Choice("Referral", "referral"),
        ),
    ),
)
VISITS = TableBlock(
    "Visits",
    rows=3,
    columns=(
        Column("time", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=5)),
        Column(
            "first",
            answer=AnswerSpec(
                ANSWER_TYPES.YES_NO, choices=(Choice("Y", "yes"), Choice("N", "no"))
            ),
        ),
    ),
)


def saved_form(connection: sqlite3.Connection) -> Form:
    form = save_form(
        connection,
        Form(
            name="Shift log",
            blocks=(FormBlock(DETAILS), FormBlock(SERVICES), FormBlock(VISITS)),
        ),
    )
    mark_printed(connection, form.form_id, form.version)
    return form


def add_sheet(  # noqa: PLR0913 (a sheet's whole contents)
    connection: sqlite3.Connection,
    tmp_path: Path,
    form: Form,
    name: str,
    answers: dict[tuple[int, int | None, int | None], tuple[str, ...]],
    status: str = CAPTURE_STATUSES.SAVED,
) -> None:
    image = tmp_path / "images" / name
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(name.encode())  # distinct content for each sheet
    capture = add_capture(connection, image)
    save_capture(
        connection,
        replace(
            capture,
            status=status,
            form_id=form.form_id,
            form_version=form.version,
            page=1,
            answers=tuple(
                CapturedAnswer(block, row, column, values=values)
                for (block, row, column), values in answers.items()
            ),
        ),
    )


SHEET_ONE = {
    (0, None, 0): ("2026/10/08",),
    (0, None, 1): ("night",),
    (1, None, None): ("food", "clothing"),
    (2, 0, 0): ("09:30",),
    (2, 0, 1): ("yes",),
    (2, 1, 0): (),
    (2, 1, 1): ("no",),  # an empty yes/no bubble reads as "no"
    (2, 2, 0): (),
    (2, 2, 1): (),
}


@pytest.fixture
def form(connection: sqlite3.Connection, tmp_path: Path) -> Form:
    form = saved_form(connection)
    add_sheet(connection, tmp_path, form, "one.jpg", SHEET_ONE)
    add_sheet(
        connection,
        tmp_path,
        form,
        "spoilt.jpg",
        SHEET_ONE,
        status=CAPTURE_STATUSES.REJECTED,
    )
    add_sheet(
        connection,
        tmp_path,
        form,
        "unchecked.jpg",
        SHEET_ONE,
        status=CAPTURE_STATUSES.READ,
    )
    return form


def test_only_saved_sheets_are_exported(
    connection: sqlite3.Connection, form: Form
) -> None:
    data = collect(connection, form)

    assert data.sheet_count == 1
    assert saved_sheet_counts(connection) == {form.form_id: 1}


def test_a_sheet_row_has_its_details_and_answers(
    connection: sqlite3.Connection, form: Form
) -> None:
    data = collect(connection, form)

    assert data.sheet_columns == [*SHEET_COLUMNS, "Date", "Shift", "services"]
    (sheet,) = data.sheets
    assert sheet["sheet_file"] == "one.jpg"
    assert sheet["form_version"] == "1"
    assert sheet["Date"] == "2026/10/08"
    assert sheet["Shift"] == "night"
    assert sheet["services"] == "food;clothing"


def test_table_rows_repeat_the_sheet_and_skip_empty_rows(
    connection: sqlite3.Connection, form: Form
) -> None:
    (visits,) = collect(connection, form).tables

    assert visits.columns == [*SHEET_COLUMNS, "row", "Date", "Shift", "time", "first"]
    assert [(row["row"], row["time"], row["first"]) for row in visits.rows] == [
        ("1", "09:30", "yes"),
        ("2", "", "no"),
    ]
    assert {row["Shift"] for row in visits.rows} == {"night"}


def test_csv_files_open_in_excel_as_utf8(
    connection: sqlite3.Connection, form: Form, tmp_path: Path
) -> None:
    written = write_csv(collect(connection, form), tmp_path / "out")

    assert [path.name for path in written] == [
        "Shift log - sheets.csv",
        "Shift log - Visits.csv",
    ]
    raw = written[0].read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with written[0].open(encoding="utf-8-sig", newline="") as file:
        (row,) = list(csv.DictReader(file))
    assert row["services"] == "food;clothing"


def test_json_nests_each_sheets_data(
    connection: sqlite3.Connection, form: Form, tmp_path: Path
) -> None:
    path = tmp_path / "out" / "data.json"

    write_json(collect(connection, form), path)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["form"] == {"id": form.form_id, "name": "Shift log"}
    (sheet,) = document["sheets"]
    assert sheet["details"] == {"Date": "2026/10/08", "Shift": "night"}
    assert sheet["answers"] == {"services": ["food", "clothing"]}
    assert sheet["tables"]["Visits"] == [
        {"row": 1, "values": {"time": "09:30", "first": "yes"}},
        {"row": 2, "values": {"time": "", "first": "no"}},
    ]


def test_sheets_from_every_version_share_the_columns(
    connection: sqlite3.Connection, form: Form, tmp_path: Path
) -> None:
    extra = Question("notes", "Notes", answer=AnswerSpec(ANSWER_TYPES.WRITTEN))
    newer = save_form(
        connection, replace(form, blocks=(*form.blocks, FormBlock(extra)))
    )
    add_sheet(connection, tmp_path, newer, "two.jpg", {(3, None, None): ("all good",)})

    data = collect(connection, newer)

    assert data.sheet_columns[-2:] == ["services", "notes"]
    assert [sheet.get("notes", "") for sheet in data.sheets] == ["", "all good"]
    assert [sheet["form_version"] for sheet in data.sheets] == ["1", "2"]


def test_a_question_cant_share_a_sheet_details_fields_name() -> None:
    clash = replace(SERVICES, name="shift")

    form = Form(name="Log", blocks=(FormBlock(DETAILS), FormBlock(clash)))

    assert form.validation_errors(set())["blocks"] == (
        'The question "shift" has the same name as a sheet details field; rename '
        "one so their data can be told apart."
    )


# --- On the Capture screen -----------------------------------------------------------


def test_exporting_csv_from_the_capture_screen(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    form: Form,
    tmp_path: Path,
) -> None:
    page = CapturePage(connection)
    qtbot.addWidget(page)
    choose = mocker.patch(
        "omr_data_collector.ui.CapturePage.choose_export",
        return_value=(form.form_id, CSV_FORMAT, None),
    )
    mocker.patch(
        "omr_data_collector.ui.CapturePage.choose_export_folder",
        return_value=tmp_path / "export",
    )
    messages: list[str] = []
    page.status_message.connect(messages.append)

    page.export_data()

    ((_, forms, sheets), _) = choose.call_args
    assert [(f.name, count) for f, count in forms] == [("Shift log", 1)]
    ((_, description),) = sheets[form.form_id]
    assert description.startswith("one.jpg: page 1, captured ")
    assert description.endswith("Date 2026/10/08 and Shift night")
    assert (tmp_path / "export" / "Shift log - sheets.csv").exists()
    assert messages == [
        f'Exported 1 sheet of "Shift log". Wrote 2 files to {tmp_path / "export"}.'
    ]


def test_exporting_json_from_the_capture_screen(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    form: Form,
    tmp_path: Path,
) -> None:
    page = CapturePage(connection)
    qtbot.addWidget(page)
    mocker.patch(
        "omr_data_collector.ui.CapturePage.choose_export",
        return_value=(form.form_id, JSON_FORMAT, None),
    )
    choose_path = mocker.patch(
        "omr_data_collector.ui.CapturePage.choose_json_path",
        return_value=tmp_path / "shift.json",
    )

    page.export_data()

    choose_path.assert_called_once_with(page, "Shift log.json")
    assert json.loads((tmp_path / "shift.json").read_text())["sheets"]


def test_the_dialog_says_when_theres_nothing_to_export(qtbot: QtBot) -> None:
    dialog = ExportDialog(None, [])
    qtbot.addWidget(dialog)

    assert not dialog.buttons.buttons()[0].isEnabled()


# --- Combining chosen sheets ---------------------------------------------------------

SHEET_TWO = {
    (0, None, 0): ("2026/10/08",),
    (0, None, 1): ("night",),
    (1, None, None): (),
    (2, 0, 0): ("23:10",),
    (2, 0, 1): ("no",),
}


def ids_by_file(connection: sqlite3.Connection) -> dict[str, str]:
    from omr_data_collector.storage.capture_store import list_captures  # noqa: PLC0415

    return {c.original_name: c.capture_id for c in list_captures(connection)}


def test_chosen_sheets_combine_into_one_in_the_order_given(
    connection: sqlite3.Connection, form: Form, tmp_path: Path
) -> None:
    add_sheet(connection, tmp_path, form, "two.jpg", SHEET_TWO)
    ids = ids_by_file(connection)

    data = collect(connection, form, [ids["two.jpg"], ids["one.jpg"]])

    assert data.sheet_count == 2
    (sheet,) = data.sheets
    assert sheet["sheet_file"] == "two.jpg;one.jpg"
    assert sheet["Date"] == "2026/10/08"  # the same on both: once
    assert sheet["services"] == "food;clothing"
    (visits,) = data.tables
    assert "combined_row" in visits.columns
    assert [
        (row["sheet_file"], row["row"], row["combined_row"], row["time"])
        for row in visits.rows
    ] == [
        ("two.jpg", "1", "1", "23:10"),
        ("one.jpg", "1", "2", "09:30"),
        ("one.jpg", "2", "3", ""),
    ]


def test_combined_values_that_differ_are_all_kept(
    connection: sqlite3.Connection, form: Form, tmp_path: Path
) -> None:
    other_day = {**SHEET_TWO, (0, None, 0): ("2026/10/09",)}
    add_sheet(connection, tmp_path, form, "two.jpg", other_day)
    ids = ids_by_file(connection)

    data = collect(connection, form, [ids["one.jpg"], ids["two.jpg"]])

    assert data.sheets[0]["Date"] == "2026/10/08;2026/10/09"
    combined = data.document["combined"]
    assert combined["details"]["Date"] == ["2026/10/08", "2026/10/09"]
    assert combined["details"]["Shift"] == "night"
    assert [row["combinedRow"] for row in combined["tables"]["Visits"]] == [1, 2, 3]


def test_only_saved_sheets_can_be_combined(
    connection: sqlite3.Connection, form: Form
) -> None:
    ids = ids_by_file(connection)

    data = collect(connection, form, [ids["spoilt.jpg"], ids["one.jpg"]])

    assert data.sheet_count == 1


def test_the_dialog_combines_the_ticked_sheets_in_list_order(qtbot: QtBot) -> None:
    form = Form(name="Shift log")
    dialog = ExportDialog(
        None,
        [(form, 3)],
        {form.form_id: [("a", "a.jpg"), ("b", "b.jpg"), ("c", "c.jpg")]},
    )
    qtbot.addWidget(dialog)
    assert not dialog.sheet_list.isEnabled()

    dialog.chosen_button.setChecked(True)

    assert dialog.sheet_list.isEnabled()
    assert not dialog.ok_button.isEnabled()  # nothing ticked yet
    for row in (0, 2):
        dialog.sheet_list.item(row).setCheckState(Qt.CheckState.Checked)
    dialog.sheet_list.setCurrentRow(2)
    dialog.move_sheet(-1)
    dialog.move_sheet(-1)

    assert dialog.ok_button.isEnabled()
    assert dialog.chosen() == (form.form_id, CSV_FORMAT, ["c", "a"])

    dialog.every_button.setChecked(True)

    assert dialog.chosen() == (form.form_id, CSV_FORMAT, None)


def test_combining_from_the_capture_screen(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    form: Form,
    tmp_path: Path,
) -> None:
    add_sheet(connection, tmp_path, form, "two.jpg", SHEET_TWO)
    ids = ids_by_file(connection)
    page = CapturePage(connection)
    qtbot.addWidget(page)
    mocker.patch(
        "omr_data_collector.ui.CapturePage.choose_export",
        return_value=(form.form_id, CSV_FORMAT, [ids["one.jpg"], ids["two.jpg"]]),
    )
    mocker.patch(
        "omr_data_collector.ui.CapturePage.choose_export_folder",
        return_value=tmp_path / "export",
    )
    messages: list[str] = []
    page.status_message.connect(messages.append)

    page.export_data()

    with (tmp_path / "export" / "Shift log - sheets.csv").open(
        encoding="utf-8-sig", newline=""
    ) as file:
        (row,) = list(csv.DictReader(file))
    assert row["sheet_file"] == "one.jpg;two.jpg"
    assert messages[0].startswith('Exported 2 sheets of "Shift log".')
