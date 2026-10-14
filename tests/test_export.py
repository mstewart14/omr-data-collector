"""Exporting checked sheets as CSV files and JSON."""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt

from omr_data_collector.constants import ANSWER_TYPES, CAPTURE_STATUSES
from omr_data_collector.export.data_export import (
    SHEET_COLUMNS,
    SHEETS_FILE,
    ExportNames,
    MissingColumn,
    collect,
    output_files,
    safe_file_name,
    saved_sheet_counts,
    spreadsheet_safe,
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
from omr_data_collector.storage.export_store import (
    load_export_names,
    save_export_names,
)
from omr_data_collector.storage.form_store import mark_printed, save_form
from omr_data_collector.ui.CapturePage import (
    CapturePage,
    default_file_name,
    mixed_layout_warning,
)
from omr_data_collector.ui.ExportDialog import CSV_FORMAT, JSON_FORMAT, ExportDialog
from omr_data_collector.ui.ExportNamesDialog import ExportNamesDialog

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from PySide6.QtWidgets import QTableWidgetItem
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
    scanned: dict[tuple[int, int | None, int | None], tuple[str, ...]] | None = None,
) -> None:
    """Add a checked sheet; its bubbles read as ``answers`` unless ``scanned`` says."""
    scanned = {**answers, **(scanned or {})}
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
                CapturedAnswer(
                    block,
                    row,
                    column,
                    scanned=scanned[block, row, column],
                    values=values,
                )
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
    (2, 1, 1): ("no",),  # an empty yes/no bubble: its "left empty" value
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

    assert visits.columns == [
        *SHEET_COLUMNS,
        "row",
        "row_corrected_answers",
        "Date",
        "Shift",
        "time",
        "first",
    ]
    assert [(row["row"], row["time"], row["first"]) for row in visits.rows] == [
        ("1", "09:30", "yes"),
        # Row 2 has only an empty yes/no bubble ("no"): nothing filled in.
    ]
    assert {row["Shift"] for row in visits.rows} == {"night"}


def test_a_row_of_only_empty_yes_no_bubbles_isnt_exported(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    form = saved_form(connection)
    marked = {**SHEET_ONE, (2, 2, 1): ("yes",)}  # row 3: only its bubble marked
    add_sheet(connection, tmp_path, form, "a.jpg", marked)

    (visits,) = collect(connection, form).tables

    assert [(row["row"], row["first"]) for row in visits.rows] == [
        ("1", "yes"),
        ("3", "yes"),
    ]


def test_an_export_is_named_for_when_and_which_form_version() -> None:
    form = Form(name="Outside / Tents", version=3)
    now = datetime(2026, 10, 14, 9, 5).astimezone()

    assert default_file_name(form, now) == "2026-10-14 0905 Outside - Tents v3"


def test_csv_files_open_in_excel_as_utf8(
    connection: sqlite3.Connection, form: Form, tmp_path: Path
) -> None:
    written = write_csv(collect(connection, form), tmp_path / "out" / "October.csv")

    # Each table's file beside the one named, after it.
    assert [path.name for path in written] == ["October.csv", "October - Visits.csv"]
    raw = written[0].read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with written[0].open(encoding="utf-8-sig", newline="") as file:
        (row,) = list(csv.DictReader(file))
    assert row["services"] == "food;clothing"


def test_a_typed_formula_is_kept_as_text_in_csv_but_not_json(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    form = saved_form(connection)
    typed = {**SHEET_ONE, (0, None, 0): ('=HYPERLINK("http://x")',)}
    add_sheet(connection, tmp_path, form, "=1+1.jpg", typed)
    data = collect(connection, form)

    sheets, _ = write_csv(data, tmp_path / "out" / "data.csv")
    write_json(data, tmp_path / "out" / "data.json")

    with sheets.open(encoding="utf-8-sig", newline="") as file:
        (row,) = list(csv.DictReader(file))
    assert row["Date"] == '\'=HYPERLINK("http://x")'
    assert row["sheet_file"] == "'=1+1.jpg"
    document = json.loads((tmp_path / "out" / "data.json").read_text())
    assert document["sheets"][0]["details"]["Date"] == '=HYPERLINK("http://x")'


@pytest.mark.parametrize(
    ("value", "written"),
    [
        ("-5", "-5"),
        ("+3.5", "+3.5"),
        ("-1e3", "-1e3"),
        ("09:30", "09:30"),
        ("-", "'-"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("+1 555 0100", "'+1 555 0100"),
        ("\tx", "'\tx"),
    ],
)
def test_only_cells_a_spreadsheet_would_run_are_changed(
    value: str, written: str
) -> None:
    assert spreadsheet_safe(value) == written


def test_two_tables_never_write_one_file(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    tables = (replace(VISITS, name="In/out"), replace(VISITS, name="in:out"))
    form = save_form(
        connection, Form(name="Log", blocks=tuple(FormBlock(t) for t in tables))
    )
    mark_printed(connection, form.form_id, form.version)

    written = write_csv(collect(connection, form), tmp_path / "Log.csv")

    assert [path.name for path in written] == [
        "Log.csv",
        "Log - In-out.csv",
        "Log - in-out (2).csv",
    ]


@pytest.mark.parametrize(
    ("name", "safe"),
    [
        ("Intake: 2026/10", "Intake- 2026-10"),
        ("tab\there", "tab-here"),
        ("CON", "_CON"),
        ("nul.txt", "_nul.txt"),
        ("CON - sheets", "CON - sheets"),
        ("...", "data"),
    ],
)
def test_file_names_are_safe_on_every_system(name: str, safe: str) -> None:
    assert safe_file_name(name) == safe


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
    assert sheet["correctedAnswers"] == []
    assert sheet["tables"]["Visits"] == [
        {"row": 1, "values": {"time": "09:30", "first": "yes"}, "correctedColumns": []},
        # Row 2 has only an empty yes/no bubble: not filled in, so not listed.
    ]


# The person checking added "clothing" and changed row 1's "first" from no to
# yes; typing in row 1's handwritten time isn't a change.
CORRECTED_SCAN = {
    (1, None, None): ("food",),
    (2, 0, 1): ("no",),
    (2, 0, 0): (),
}


def test_answers_changed_by_hand_are_counted(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    form = saved_form(connection)
    add_sheet(connection, tmp_path, form, "one.jpg", SHEET_ONE, scanned=CORRECTED_SCAN)

    data = collect(connection, form)

    assert data.sheets[0]["corrected_answers"] == "2"
    (visits,) = data.tables
    assert [row["row_corrected_answers"] for row in visits.rows] == ["1"]
    assert {row["corrected_answers"] for row in visits.rows} == {"2"}


def test_json_names_the_answers_changed_by_hand(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    form = saved_form(connection)
    add_sheet(connection, tmp_path, form, "one.jpg", SHEET_ONE, scanned=CORRECTED_SCAN)
    path = tmp_path / "data.json"

    write_json(collect(connection, form), path, RENAMED)

    (sheet,) = json.loads(path.read_text(encoding="utf-8"))["sheets"]
    assert sheet["correctedAnswers"] == ["Services used"]
    assert [row["correctedColumns"] for row in sheet["tables"]["Visits"]] == [["first"]]


def test_combined_sheets_add_up_their_changes(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    form = saved_form(connection)
    add_sheet(connection, tmp_path, form, "one.jpg", SHEET_ONE, scanned=CORRECTED_SCAN)
    add_sheet(
        connection,
        tmp_path,
        form,
        "two.jpg",
        SHEET_TWO,
        scanned={(1, None, None): ("food",)},  # unmarked by hand
    )
    ids = ids_by_file(connection)

    data = collect(connection, form, [ids["one.jpg"], ids["two.jpg"]])

    assert data.sheets[0]["corrected_answers"] == "3"
    assert data.document["combined"]["correctedAnswers"] == ["services"]


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
        return_value=(form.form_id, CSV_FORMAT, None, True),
    )
    choose_path = mocker.patch(
        "omr_data_collector.ui.CapturePage.choose_export_path",
        return_value=tmp_path / "export" / "October.csv",
    )
    messages: list[str] = []
    page.status_message.connect(messages.append)

    page.export_data()

    ((_, file_format, suggested), _) = choose_path.call_args
    assert (file_format, suggested.name[16:]) == (CSV_FORMAT, "Shift log v1")
    ((_, forms, sheets, _, _), _) = choose.call_args
    assert [(f.name, count) for f, count in forms] == [("Shift log", 1)]
    ((_, description),) = sheets[form.form_id]
    assert description.startswith("one.jpg: page 1, captured ")
    assert description.endswith("Date 2026/10/08 and Shift night")
    assert (tmp_path / "export" / "October.csv").exists()
    assert (tmp_path / "export" / "October - Visits.csv").exists()
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
        return_value=(form.form_id, JSON_FORMAT, None, True),
    )
    choose_path = mocker.patch(
        "omr_data_collector.ui.CapturePage.choose_export_path",
        return_value=tmp_path / "shift.json",
    )

    page.export_data()

    ((_, file_format, suggested), _) = choose_path.call_args
    assert (file_format, suggested.name[16:]) == (JSON_FORMAT, "Shift log v1")
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
    assert [row["combinedRow"] for row in combined["tables"]["Visits"]] == [1, 2]


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
    assert dialog.chosen() == (form.form_id, CSV_FORMAT, ["c", "a"], True)

    dialog.every_button.setChecked(True)

    assert dialog.chosen() == (form.form_id, CSV_FORMAT, None, True)


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
        return_value=(form.form_id, CSV_FORMAT, [ids["one.jpg"], ids["two.jpg"]], True),
    )
    mocker.patch(
        "omr_data_collector.ui.CapturePage.choose_export_path",
        return_value=tmp_path / "export" / "Shift log.csv",
    )
    messages: list[str] = []
    page.status_message.connect(messages.append)

    page.export_data()

    with (tmp_path / "export" / "Shift log.csv").open(
        encoding="utf-8-sig", newline=""
    ) as file:
        (row,) = list(csv.DictReader(file))
    assert row["sheet_file"] == "one.jpg;two.jpg"
    assert messages[0].startswith('Exported 2 sheets of "Shift log".')


# --- Export columns: chosen, ordered and renamed ----------------------------------


def test_the_files_and_their_columns(
    connection: sqlite3.Connection, form: Form
) -> None:
    files = output_files(connection, form)

    assert [f.key for f in files] == [SHEETS_FILE, "Visits"]
    assert files[0].columns[-3:] == ("Date", "Shift", "services")
    first_row_column = len(SHEET_COLUMNS)
    assert files[1].columns[first_row_column : first_row_column + 3] == (
        "row",
        "combined_row",
        "row_corrected_answers",
    )


RENAMED = ExportNames(
    columns={
        SHEETS_FILE: {"sheet_id": "id", "services": "Services used"},
        "Visits": {"time": "Time of visit"},
    },
)


def test_csv_columns_take_their_export_names(
    connection: sqlite3.Connection, form: Form, tmp_path: Path
) -> None:
    written = write_csv(collect(connection, form), tmp_path / "intake.csv", RENAMED)

    with written[0].open(encoding="utf-8-sig", newline="") as file:
        (row,) = list(csv.DictReader(file))
    assert row["id"]
    assert row["Services used"] == "food;clothing"
    assert "sheet_id" not in row
    with written[1].open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["Time of visit"] == "09:30"


def test_json_takes_the_export_names(
    connection: sqlite3.Connection, form: Form, tmp_path: Path
) -> None:
    path = tmp_path / "intake data.json"

    write_json(collect(connection, form), path, RENAMED)

    (sheet,) = json.loads(path.read_text(encoding="utf-8"))["sheets"]
    assert sheet["answers"] == {"Services used": ["food", "clothing"]}
    assert sheet["tables"]["Visits"][0]["values"]["Time of visit"] == "09:30"


CHOSEN = ExportNames(
    left_out={SHEETS_FILE: ["sheet_file", "Shift"], "Visits": ["first"]},
    order={SHEETS_FILE: ["services", "Date"]},
)


def test_csv_has_only_the_chosen_columns_in_the_chosen_order(
    connection: sqlite3.Connection, form: Form, tmp_path: Path
) -> None:
    sheets, visits = write_csv(collect(connection, form), tmp_path / "a.csv", CHOSEN)

    with sheets.open(encoding="utf-8-sig", newline="") as file:
        header = next(csv.reader(file))
    # The columns ordered first, then the rest in their own order.
    assert header[:3] == ["services", "Date", "sheet_id"]
    assert "sheet_file" not in header
    assert "Shift" not in header
    with visits.open(encoding="utf-8-sig", newline="") as file:
        assert "first" not in next(csv.reader(file))


def test_json_has_only_the_chosen_answers_in_the_chosen_order(
    connection: sqlite3.Connection, form: Form, tmp_path: Path
) -> None:
    path = tmp_path / "a.json"
    names = replace(CHOSEN, order={SHEETS_FILE: ["Shift", "Date"]}, left_out={})

    write_json(collect(connection, form), path, CHOSEN)
    (sheet,) = json.loads(path.read_text(encoding="utf-8"))["sheets"]
    assert list(sheet["details"]) == ["Date"]
    assert "sheetFile" in sheet  # its structure is fixed
    assert list(sheet["tables"]["Visits"][0]["values"]) == ["time"]

    write_json(collect(connection, form), path, names)
    (sheet,) = json.loads(path.read_text(encoding="utf-8"))["sheets"]
    assert list(sheet["details"]) == ["Shift", "Date"]


def test_export_names_are_kept_for_the_form(
    connection: sqlite3.Connection, form: Form
) -> None:
    assert load_export_names(connection, form.form_id) == ExportNames()
    both = replace(CHOSEN, columns=RENAMED.columns)

    save_export_names(connection, form.form_id, both)

    assert load_export_names(connection, form.form_id) == both


def test_file_names_kept_by_earlier_versions_are_ignored() -> None:
    old = {"files": {SHEETS_FILE: "intake"}, "columns": {SHEETS_FILE: {"a": "b"}}}

    assert ExportNames.from_dict(old) == ExportNames(columns={SHEETS_FILE: {"a": "b"}})


def names_dialog(
    qtbot: QtBot, connection: sqlite3.Connection, form: Form, names: ExportNames
) -> ExportNamesDialog:
    dialog = ExportNamesDialog(None, output_files(connection, form), names)
    qtbot.addWidget(dialog)
    return dialog


def row_named(dialog: ExportNamesDialog, key: str, default: str) -> int:
    return next(
        row
        for row in range(dialog.table.rowCount())
        if dialog._row_data(row) == (key, default)  # noqa: SLF001
    )


def name_cell(dialog: ExportNamesDialog, key: str, default: str) -> QTableWidgetItem:
    item = dialog.table.item(row_named(dialog, key, default), 2)
    assert item is not None
    return item


def tick_cell(dialog: ExportNamesDialog, key: str, default: str) -> QTableWidgetItem:
    item = dialog.table.item(row_named(dialog, key, default), 1)
    assert item is not None
    return item


def test_the_names_dialog_keeps_only_changed_names(
    qtbot: QtBot, connection: sqlite3.Connection, form: Form
) -> None:
    dialog = names_dialog(qtbot, connection, form, RENAMED)
    assert name_cell(dialog, SHEETS_FILE, "services").text() == "Services used"
    first = dialog.table.item(0, 0)
    assert first is not None
    assert first.text() == "Sheets"  # only columns are listed

    name_cell(dialog, SHEETS_FILE, "Date").setText("Date")
    name_cell(dialog, SHEETS_FILE, "Shift").setText(" shift ")
    dialog.accept()

    accepted = dialog.names()
    assert accepted is not None
    assert accepted.columns[SHEETS_FILE] == {
        "sheet_id": "id",
        "services": "Services used",
        "Shift": "shift",
    }
    assert accepted.left_out == {}
    assert accepted.order == {}


def test_the_names_dialog_chooses_and_orders_the_columns(
    qtbot: QtBot, connection: sqlite3.Connection, form: Form
) -> None:
    dialog = names_dialog(qtbot, connection, form, ExportNames())
    assert tick_cell(dialog, SHEETS_FILE, "Shift").checkState() == Qt.CheckState.Checked

    tick_cell(dialog, SHEETS_FILE, "Shift").setCheckState(Qt.CheckState.Unchecked)
    dialog.table.setCurrentCell(row_named(dialog, SHEETS_FILE, "services"), 2)
    assert not dialog.move_down_button.isEnabled()  # the sheets file's last
    dialog.move_column(-1)
    dialog.accept()

    accepted = dialog.names()
    assert accepted is not None
    assert accepted.left_out == {SHEETS_FILE: ["Shift"]}
    assert accepted.order[SHEETS_FILE][-3:] == ["Date", "services", "Shift"]
    assert "Visits" not in accepted.order

    # Shown as kept, and Reset puts every column back, in its own order.
    again = names_dialog(qtbot, connection, form, accepted)
    assert row_named(again, SHEETS_FILE, "services") < row_named(
        again, SHEETS_FILE, "Shift"
    )
    assert tick_cell(again, SHEETS_FILE, "Shift").checkState() == (
        Qt.CheckState.Unchecked
    )
    again.reset()
    again.accept()
    assert again.names() == ExportNames()


def test_a_column_only_moves_among_its_own_files(
    qtbot: QtBot, connection: sqlite3.Connection, form: Form
) -> None:
    dialog = names_dialog(qtbot, connection, form, ExportNames())
    first_of_visits = row_named(dialog, "Visits", "sheet_id")
    dialog.table.setCurrentCell(first_of_visits, 2)

    dialog.move_column(-1)

    assert not dialog.move_up_button.isEnabled()
    assert dialog.table.currentRow() == first_of_visits


def test_the_names_dialog_refuses_two_columns_with_one_name(
    qtbot: QtBot, connection: sqlite3.Connection, form: Form
) -> None:
    dialog = names_dialog(qtbot, connection, form, ExportNames())

    name_cell(dialog, SHEETS_FILE, "Shift").setText("date")
    dialog.accept()

    assert dialog.names() is None
    assert dialog.error_label.text() == (
        'Two columns of the sheets file would both be called "date".'
    )

    # A column left out takes no name.
    tick_cell(dialog, SHEETS_FILE, "Date").setCheckState(Qt.CheckState.Unchecked)
    dialog.accept()
    assert dialog.names() is not None


def test_the_names_dialog_needs_a_column_in_each_file(
    qtbot: QtBot, connection: sqlite3.Connection, form: Form
) -> None:
    dialog = names_dialog(qtbot, connection, form, ExportNames())
    for row in range(dialog.table.rowCount()):
        key, default = dialog._row_data(row)  # noqa: SLF001
        if key == "Visits":
            tick_cell(dialog, key, default).setCheckState(Qt.CheckState.Unchecked)

    dialog.accept()

    assert dialog.names() is None
    assert dialog.error_label.text() == (
        'Tick at least one column of the table "Visits".'
    )


def test_names_set_from_the_capture_screen_are_used_by_exports(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    form: Form,
    tmp_path: Path,
) -> None:
    page = CapturePage(connection)
    qtbot.addWidget(page)
    mocker.patch(
        "omr_data_collector.ui.CapturePage.choose_export_names", return_value=RENAMED
    )

    page.edit_export_names(form)

    assert load_export_names(connection, form.form_id) == RENAMED
    mocker.patch(
        "omr_data_collector.ui.CapturePage.choose_export",
        return_value=(form.form_id, CSV_FORMAT, None, True),
    )
    mocker.patch(
        "omr_data_collector.ui.CapturePage.choose_export_path",
        return_value=tmp_path / "export" / "intake.csv",
    )

    page.export_data()

    with (tmp_path / "export" / "intake.csv").open(encoding="utf-8-sig") as file:
        assert "Services used" in file.readline()


def test_table_files_beside_it_are_only_replaced_if_you_say(
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
        return_value=(form.form_id, CSV_FORMAT, None, True),
    )
    mocker.patch(
        "omr_data_collector.ui.CapturePage.choose_export_path",
        return_value=tmp_path / "Log.csv",
    )
    (tmp_path / "Log - Visits.csv").write_text("keep me")
    confirm = mocker.patch(
        "omr_data_collector.ui.CapturePage.confirm_destructive", return_value=False
    )

    page.export_data()

    assert "Log - Visits.csv" in confirm.call_args.args[2]
    assert (tmp_path / "Log - Visits.csv").read_text() == "keep me"
    assert not (tmp_path / "Log.csv").exists()

    confirm.return_value = True
    page.export_data()

    assert (tmp_path / "Log - Visits.csv").read_text() != "keep me"


# --- Sheets from versions with different columns -------------------------------------


@pytest.fixture
def two_versions(
    connection: sqlite3.Connection, form: Form, tmp_path: Path
) -> tuple[Form, dict[str, str]]:
    """Version 2 adds the question "notes"; a sheet from each version."""
    extra = Question("notes", "Notes", answer=AnswerSpec(ANSWER_TYPES.WRITTEN))
    newer = save_form(
        connection, replace(form, blocks=(*form.blocks, FormBlock(extra)))
    )
    add_sheet(connection, tmp_path, newer, "two.jpg", {(3, None, None): ("ok",)})
    return newer, ids_by_file(connection)


def test_sheets_from_versions_with_different_columns_are_named(
    connection: sqlite3.Connection, two_versions: tuple[Form, dict[str, str]]
) -> None:
    newer, ids = two_versions

    data = collect(connection, newer)

    assert data.missing == [MissingColumn(None, "notes", (1,))]
    assert mixed_layout_warning(data) == (
        "Warning: these sheets were printed from versions of the form with "
        "different columns, so they don't all line up. Columns a sheet's version "
        'didn\'t have are left blank for it: "notes" (not on version 1).'
    )
    # One version's sheets alone share their layout.
    assert collect(connection, newer, [ids["two.jpg"]]).missing == []
    assert mixed_layout_warning(collect(connection, newer, [ids["one.jpg"]])) == ""


def test_the_export_dialog_warns_about_mixed_versions(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    two_versions: tuple[Form, dict[str, str]],
) -> None:
    newer, _ = two_versions
    page = CapturePage(connection)
    qtbot.addWidget(page)
    shown: list[ExportDialog] = []

    def look(dialog: ExportDialog) -> int:
        shown.append(dialog)
        return 0  # cancelled

    mocker.patch.object(ExportDialog, "exec", look)

    page.export_data()

    (dialog,) = shown
    assert dialog.warning.text().startswith("Warning: these sheets were printed")
    assert not dialog.warning.isHidden()
    assert dialog.ok_button.accessibleDescription() == dialog.warning.text()

    dialog.chosen_button.setChecked(True)
    dialog.sheet_list.item(1).setCheckState(Qt.CheckState.Checked)  # two.jpg

    assert dialog.warning.isHidden()
    assert newer.name in dialog.form_combo.currentText()


# --- Older sheets exported with the latest version's saved values ---------------


@pytest.fixture
def resaved(connection: sqlite3.Connection, form: Form) -> Form:
    """Version 2 saves "first" as 1 or nothing, and services as letters."""
    first = Column(
        "first",
        answer=AnswerSpec(
            ANSWER_TYPES.YES_NO, choices=(Choice("Y", "1"), Choice("N", ""))
        ),
    )
    visits = replace(VISITS, columns=(VISITS.columns[0], first))
    services = replace(
        SERVICES,
        answer=replace(
            SERVICES.answer,
            choices=(
                Choice("Food", "F"),
                Choice("Clothing", "C"),
                Choice("Referral", "R"),
            ),
        ),
    )
    return save_form(
        connection,
        replace(
            form, blocks=(FormBlock(DETAILS), FormBlock(services), FormBlock(visits))
        ),
    )


def test_older_sheets_can_take_the_latest_saved_values(
    connection: sqlite3.Connection, resaved: Form
) -> None:
    data = collect(connection, resaved, latest_values=True)

    (sheet,) = data.sheets
    assert sheet["form_version"] == "1"
    assert sheet["services"] == "F;C"
    (visits,) = data.tables
    assert [(row["row"], row["first"]) for row in visits.rows] == [("1", "1")]
    (document,) = data.document["sheets"]
    assert document["answers"]["services"] == ["F", "C"]
    # An empty bubble saves nothing now: no "no" left in the export.
    assert "no" not in json.dumps(data.document)


def test_or_keep_what_their_own_version_saved(
    connection: sqlite3.Connection, resaved: Form
) -> None:
    data = collect(connection, resaved)

    assert data.sheets[0]["services"] == "food;clothing"
    assert [row["first"] for row in data.tables[0].rows] == ["yes"]


def test_answers_whose_choices_dont_line_up_keep_their_values(
    connection: sqlite3.Connection, form: Form
) -> None:
    services = replace(
        SERVICES,
        answer=replace(SERVICES.answer, choices=(Choice("Food", "F"), Choice("Other"))),
    )
    blocks = (FormBlock(DETAILS), FormBlock(services), FormBlock(VISITS))
    newer = save_form(connection, replace(form, blocks=blocks))

    data = collect(connection, newer, latest_values=True)

    assert data.sheets[0]["services"] == "food;clothing"


def test_the_export_dialog_uses_the_latest_values_unless_unticked(
    qtbot: QtBot,
) -> None:
    form = Form(name="Shift log")
    dialog = ExportDialog(None, [(form, 1)])
    qtbot.addWidget(dialog)
    assert dialog.latest_values_box.isChecked()

    dialog.latest_values_box.setChecked(False)

    assert dialog.chosen() == (form.form_id, CSV_FORMAT, None, False)
