"""The data from a form's checked sheets, as CSV files or a JSON file.

Only sheets saved on the Capture screen count; rejected ones and ones not yet
checked are left out. A form's sheets may come from several versions of it, so
the columns are every question, sheet detail field and table column any of
those versions has, in the latest version's order.

- Sheets: one row per captured page, with its sheet details and the answers to
  the questions on it.
- Tables: one row per table row with anything filled in, repeating the sheet it
  came from and the sheet's details, so each row can be analysed on its own.

Each sheet and table row says how many of its answers the person checking it
changed from what the bubbles read as (CORRECTED_COLUMN, ROW_CORRECTED_COLUMN),
and the JSON names them: a measure of how often reading needed help, and of
which answers people fill in badly.

CSV cells a spreadsheet would run as a formula (starting "=", "+", "-" or "@",
other than plain numbers) start with an apostrophe, which spreadsheets show
as text: the values come from handwriting and file names, and a formula in
one could run when the file is opened. JSON keeps the values as they are.

Answers with several choices marked are joined with MULTIPLE_SEPARATOR in CSV,
and are lists in JSON. Column names are the names given in the editors; the
columns describing the sheet itself have fixed names, the same in every
language, so analysis scripts can rely on them.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from omr_data_collector.constants import ANSWER_TYPES, CAPTURE_STATUSES
from omr_data_collector.models.Question import Question
from omr_data_collector.models.SheetDetails import SheetDetails
from omr_data_collector.models.TableBlock import TableBlock
from omr_data_collector.storage.capture_store import list_captures
from omr_data_collector.storage.form_store import load_form_version

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from omr_data_collector.models.AnswerSpec import AnswerSpec
    from omr_data_collector.models.Capture import Capture
    from omr_data_collector.models.Form import Form

MULTIPLE_SEPARATOR = ";"
# The columns describing each sheet, before its answers.
CORRECTED_COLUMN = "corrected_answers"
SHEET_COLUMNS = (
    "sheet_id",
    "sheet_file",
    "form_version",
    "page",
    "captured_at",
    CORRECTED_COLUMN,
)
ROW_COLUMN = "row"
# How many of a table row's answers were changed by hand.
ROW_CORRECTED_COLUMN = "row_corrected_answers"
# When chosen sheets are combined: each table row's place in the combined rows.
COMBINED_ROW_COLUMN = "combined_row"
# Excel only reads a CSV file as UTF-8 when it starts with a byte order mark.
CSV_ENCODING = "utf-8-sig"
# A spreadsheet runs a cell starting with one of these as a formula, so a value
# typed in from a sheet, or an image's file name, could run one ("CSV
# injection"). Such cells get a leading apostrophe, which spreadsheets show as
# text; plain numbers like -5 are left alone.
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
NUMBER = re.compile(r"[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?")
# Names Windows reserves for devices, whatever the extension.
WINDOWS_RESERVED_NAMES = re.compile(
    r"(CON|PRN|AUX|NUL|COM\d|LPT\d)(\..*)?", re.IGNORECASE
)


# The keys of a form's outputs, for naming them: the sheets file, the JSON file,
# and each table's file under its table's name.
SHEETS_FILE, JSON_FILE = "sheets", "json"


@dataclass
class ExportNames:
    """Names given to a form's outputs in place of the defaults.

    ``files`` maps an output's key (SHEETS_FILE, JSON_FILE or a table's name)
    to a file name, without its extension; ``columns`` maps an output's key to
    {default column name: name to use}. Anything not named keeps its default.
    """

    files: dict[str, str] = field(default_factory=dict)
    columns: dict[str, dict[str, str]] = field(default_factory=dict)

    def file_name(self, key: str, default: str) -> str:
        return self.files.get(key) or default

    def column(self, key: str, default: str) -> str:
        return self.columns.get(key, {}).get(default) or default

    def to_dict(self) -> dict[str, Any]:
        return {"files": self.files, "columns": self.columns}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExportNames:
        return cls(
            files=dict(data.get("files", {})),
            columns={
                key: dict(names) for key, names in data.get("columns", {}).items()
            },
        )


@dataclass(frozen=True)
class OutputFile:
    """One output a form's data is exported to, and its default names."""

    key: str
    default_name: str
    columns: tuple[str, ...]


def output_files(connection: sqlite3.Connection, form: Form) -> list[OutputFile]:
    """Every file a form's data can be exported to, with its columns.

    The CSV files first (the sheets file, then each table's), then the JSON
    file, whose columns are the sheets file's; its structure is fixed.
    """
    data = collect(connection, form)
    base = form.name
    files = [OutputFile(SHEETS_FILE, f"{base} - sheets", tuple(data.sheet_columns))]
    for table in data.tables:
        columns = list(table.columns)
        # combined_row is only there when chosen sheets are combined.
        columns.insert(columns.index(ROW_COLUMN) + 1, COMBINED_ROW_COLUMN)
        files.append(OutputFile(table.name, f"{base} - {table.name}", tuple(columns)))
    files.append(OutputFile(JSON_FILE, base, ()))
    return files


@dataclass
class TableData:
    name: str
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)


@dataclass
class FormData:
    """A form's checked sheets, ready to write."""

    form: Form
    sheet_columns: list[str]
    sheets: list[dict[str, str]]
    tables: list[TableData]
    # The same data nested, for JSON.
    document: dict[str, Any]
    # How many captured sheets went in (combined ones make one row).
    sheet_count: int = 0


def saved_sheet_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """How many checked and saved sheets each form has, by form ID."""
    counts: dict[str, int] = {}
    for capture in list_captures(connection):
        if capture.status == CAPTURE_STATUSES.SAVED and capture.form_id:
            counts[capture.form_id] = counts.get(capture.form_id, 0) + 1
    return counts


def collect(
    connection: sqlite3.Connection, form: Form, chosen: list[str] | None = None
) -> FormData:
    """Gather the checked sheets of ``form`` (its latest version), all versions.

    With ``chosen`` (capture IDs, in order), only those sheets are gathered and
    they are combined into one: a single row of sheet details and answers, and
    their table rows one after another, numbered on in ``COMBINED_ROW_COLUMN``.
    """
    saved = {
        capture.capture_id: capture
        for capture in list_captures(connection)
        if capture.status == CAPTURE_STATUSES.SAVED and capture.form_id == form.form_id
    }
    captures = (
        list(saved.values())
        if chosen is None
        else [saved[capture_id] for capture_id in chosen if capture_id in saved]
    )
    versions: dict[int, Form] = {form.version: form}
    for capture in captures:
        version = capture.form_version
        if version is not None and version not in versions:
            loaded = load_form_version(connection, form.form_id, version)
            if loaded is not None:
                versions[version] = loaded
    ordered = [versions[number] for number in sorted(versions, reverse=True)]
    detail_columns, question_columns, table_columns = _columns(ordered)
    combined = chosen is not None
    row_columns = [ROW_COLUMN, COMBINED_ROW_COLUMN] if combined else [ROW_COLUMN]
    row_columns.append(ROW_CORRECTED_COLUMN)

    sheets: list[dict[str, str]] = []
    tables = {
        name: TableData(name, [*SHEET_COLUMNS, *row_columns, *detail_columns, *columns])
        for name, columns in table_columns.items()
    }
    documents = []
    for capture in captures:
        version_form = versions.get(capture.form_version or 0)
        if version_form is None:
            continue
        sheet, document = _sheet(capture, version_form)
        sheets.append(
            {
                **sheet["meta"],
                **_flat(sheet["details"]),
                **_flat(sheet["answers"]),
            }
        )
        for name, rows in sheet["tables"].items():
            table = tables[name]
            for number, values, corrected in rows:
                row = {
                    **sheet["meta"],
                    ROW_COLUMN: str(number),
                    ROW_CORRECTED_COLUMN: str(len(corrected)),
                    **_flat(sheet["details"]),
                    **_flat(values),
                }
                if combined:
                    row[COMBINED_ROW_COLUMN] = str(len(table.rows) + 1)
                table.rows.append(row)
        documents.append(document)
    sheet_columns = [*SHEET_COLUMNS, *detail_columns, *question_columns]
    document: dict[str, Any] = {
        "form": {"id": form.form_id, "name": form.name},
        "exportedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "sheets": documents,
    }
    if combined:
        document["combined"] = _combined_document(documents)
    return FormData(
        form=form,
        sheet_columns=sheet_columns,
        sheets=[_merged(sheets, sheet_columns)] if combined and sheets else sheets,
        tables=list(tables.values()),
        document=document,
        sheet_count=len(documents),
    )


def _merged(rows: list[dict[str, str]], columns: list[str]) -> dict[str, str]:
    """Several sheets' rows as one: each column's different values, in order.

    A value the sheets agree on appears once; different ones are all kept,
    joined with MULTIPLE_SEPARATOR, so a clash (two dates, say) stays visible.
    """
    merged = {}
    for column in columns:
        if column == CORRECTED_COLUMN:
            merged[column] = str(sum(int(row.get(column) or 0) for row in rows))
            continue
        values: list[str] = []
        for row in rows:
            value = row.get(column, "")
            if value and value not in values:
                values.append(value)
        merged[column] = MULTIPLE_SEPARATOR.join(values)
    return merged


def _combined_document(documents: list[dict[str, Any]]) -> dict[str, Any]:
    """The chosen sheets as one, for JSON.

    Details and answers are merged (a value, or a list where the sheets
    differ), and every table row follows the last, in the sheets' order.
    """

    def merge(key: str) -> dict[str, Any]:
        merged: dict[str, list[Any]] = {}
        for document in documents:
            for name, value in document[key].items():
                found = merged.setdefault(name, [])
                if value not in ("", []) and value not in found:
                    found.append(value)
        return {
            name: (values[0] if len(values) == 1 else values if values else "")
            for name, values in merged.items()
        }

    tables: dict[str, list[dict[str, Any]]] = {}
    for document in documents:
        for name, rows in document["tables"].items():
            combined_rows = tables.setdefault(name, [])
            for row in rows:
                combined_rows.append(
                    {
                        "sheetId": document["sheetId"],
                        "row": row["row"],
                        "combinedRow": len(combined_rows) + 1,
                        "values": row["values"],
                        "correctedColumns": row["correctedColumns"],
                    }
                )
    corrected: list[str] = []
    for document in documents:
        corrected.extend(
            name for name in document["correctedAnswers"] if name not in corrected
        )
    return {
        "sheetIds": [document["sheetId"] for document in documents],
        "details": merge("details"),
        "answers": merge("answers"),
        "correctedAnswers": corrected,
        "tables": tables,
    }


def write_csv(
    data: FormData, folder: Path, names: ExportNames | None = None
) -> list[Path]:
    """Write the sheets file and one file per table into ``folder``.

    ``names`` renames files and columns from their defaults.
    """
    names = names or ExportNames()
    folder.mkdir(parents=True, exist_ok=True)
    base = data.form.name
    outputs = [
        (
            names.file_name(SHEETS_FILE, f"{base} - sheets"),
            data.sheet_columns,
            data.sheets,
            SHEETS_FILE,
        ),
        *(
            (
                names.file_name(table.name, f"{base} - {table.name}"),
                table.columns,
                table.rows,
                table.name,
            )
            for table in data.tables
        ),
    ]
    written: list[Path] = []
    used: set[str] = set()
    for name, columns, rows, key in outputs:
        # Never one file over another: a table called "sheets" would otherwise
        # be written over the sheets file. Compared ignoring case, as Windows
        # and macOS name files.
        stem = safe_file_name(name)
        unique, number = stem, 2
        while unique.casefold() in used:
            unique, number = f"{stem} ({number})", number + 1
        used.add(unique.casefold())
        path = folder / f"{unique}.csv"
        _write_rows(path, columns, rows, names, key)
        written.append(path)
    return written


def json_file_name(form: Form, names: ExportNames | None = None) -> str:
    """The JSON file's name, extension included."""
    name = (names or ExportNames()).file_name(JSON_FILE, form.name)
    return f"{safe_file_name(name)}.json"


def write_json(data: FormData, path: Path, names: ExportNames | None = None) -> None:
    """Write the nested data; ``names`` renames the answers' keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    document = _renamed_document(data.document, names or ExportNames())
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _renamed_document(document: dict[str, Any], names: ExportNames) -> dict[str, Any]:
    """The JSON document with question, field and table column keys renamed."""

    def rename(values: dict[str, Any], key: str) -> dict[str, Any]:
        return {names.column(key, name): value for name, value in values.items()}

    def sheet(entry: dict[str, Any]) -> dict[str, Any]:
        return {
            **entry,
            "details": rename(entry["details"], SHEETS_FILE),
            "answers": rename(entry["answers"], SHEETS_FILE),
            "correctedAnswers": [
                names.column(SHEETS_FILE, name) for name in entry["correctedAnswers"]
            ],
            "tables": {
                table: [
                    {
                        **row,
                        "values": rename(row["values"], table),
                        "correctedColumns": [
                            names.column(table, name)
                            for name in row["correctedColumns"]
                        ],
                    }
                    for row in rows
                ]
                for table, rows in entry["tables"].items()
            },
        }

    renamed = {**document, "sheets": [sheet(entry) for entry in document["sheets"]]}
    if "combined" in document:
        renamed["combined"] = sheet(document["combined"])
    return renamed


def safe_file_name(name: str) -> str:
    """A name made safe to use in a file name on any system."""
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", name).strip(" .-") or "data"
    return f"_{safe}" if WINDOWS_RESERVED_NAMES.fullmatch(safe) else safe


def spreadsheet_safe(value: str) -> str:
    """``value`` as a CSV cell no spreadsheet will run as a formula."""
    if value.startswith(FORMULA_STARTS) and not NUMBER.fullmatch(value):
        return f"'{value}"
    return value


def _write_rows(
    path: Path,
    columns: list[str],
    rows: list[dict[str, str]],
    names: ExportNames,
    key: str,
) -> None:
    headers = [spreadsheet_safe(names.column(key, column)) for column in columns]
    with path.open("w", newline="", encoding=CSV_ENCODING) as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(
            [spreadsheet_safe(row.get(column, "")) for column in columns]
            for row in rows
        )


def _columns(
    versions: list[Form],
) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Every sheet detail, question and table column name, latest version first."""
    details: list[str] = []
    questions: list[str] = []
    tables: dict[str, list[str]] = {}

    def add(names: list[str], name: str) -> None:
        if name not in names:
            names.append(name)

    for form in versions:
        for block in form.blocks:
            content = block.content
            if isinstance(content, SheetDetails):
                for column in content.fields:
                    add(details, column.name)
            elif isinstance(content, Question):
                add(questions, content.name)
            elif isinstance(content, TableBlock):
                columns = tables.setdefault(content.name, [])
                for column in content.columns:
                    add(columns, column.name)
    return details, questions, tables


def _sheet(capture: Capture, form: Form) -> tuple[dict[str, Any], dict[str, Any]]:
    """One sheet's data, grouped (for CSV rows) and as a JSON object."""
    details: dict[str, Any] = {}
    answers: dict[str, Any] = {}
    # Sheet details fields and questions changed by hand.
    corrected: list[str] = []
    tables: dict[str, dict[int, dict[str, Any]]] = {}
    # Each table row's columns changed by hand.
    corrected_cells: dict[str, dict[int, list[str]]] = {}
    for answer in capture.answers:
        if not 0 <= answer.block_index < len(form.blocks):
            continue
        content = form.blocks[answer.block_index].content
        if isinstance(content, SheetDetails) and answer.column is not None:
            column = content.fields[answer.column]
            details[column.name] = _value(column.answer, answer.values)
            if answer.changed_by_hand(column.answer):
                corrected.append(column.name)
        elif isinstance(content, Question):
            answers[content.name] = _value(content.answer, answer.values)
            if answer.changed_by_hand(content.answer):
                corrected.append(content.name)
        elif (
            isinstance(content, TableBlock)
            and answer.column is not None
            and answer.table_row is not None
        ):
            column = content.columns[answer.column]
            row = tables.setdefault(content.name, {}).setdefault(answer.table_row, {})
            row[column.name] = _value(column.answer, answer.values)
            cells = corrected_cells.setdefault(content.name, {})
            changed = cells.setdefault(answer.table_row, [])
            if answer.changed_by_hand(column.answer):
                changed.append(column.name)
    # A row emptied by hand drops out, but still counts as corrected.
    corrected_count = len(corrected) + sum(
        len(columns) for cells in corrected_cells.values() for columns in cells.values()
    )
    meta = {
        "sheet_id": capture.capture_id,
        "sheet_file": capture.original_name,
        "form_version": str(capture.form_version),
        "page": str(capture.page),
        "captured_at": capture.added_at,
        CORRECTED_COLUMN: str(corrected_count),
    }
    filled = {
        name: [
            (number + 1, values, corrected_cells.get(name, {}).get(number, []))
            for number, values in sorted(rows.items())
            if any(values.values())
        ]
        for name, rows in tables.items()
    }
    grouped = {"meta": meta, "details": details, "answers": answers, "tables": filled}
    document = {
        "sheetId": capture.capture_id,
        "sheetFile": capture.original_name,
        "formVersion": capture.form_version,
        "page": capture.page,
        "capturedAt": capture.added_at,
        "details": details,
        "answers": answers,
        "correctedAnswers": corrected,
        "tables": {
            name: [
                {"row": number, "values": values, "correctedColumns": changed}
                for number, values, changed in rows
            ]
            for name, rows in filled.items()
        },
    }
    return grouped, document


def _value(spec: AnswerSpec, values: tuple[str, ...]) -> str | list[str]:
    """An answer's value: a list for any number of choices, else one string."""
    if spec.answer_type == ANSWER_TYPES.MANY_CHOICES:
        return list(values)
    return values[0] if values else ""


def _flat(values: dict[str, Any]) -> dict[str, str]:
    """Values for a CSV row: lists joined with MULTIPLE_SEPARATOR."""
    return {
        name: MULTIPLE_SEPARATOR.join(value) if isinstance(value, list) else value
        for name, value in values.items()
    }
