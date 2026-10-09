"""The data from a form's checked sheets, as CSV files or a JSON file.

Only sheets saved on the Capture screen count; rejected ones and ones not yet
checked are left out. A form's sheets may come from several versions of it, so
the columns are every question, sheet detail field and table column any of
those versions has, in the latest version's order.

- Sheets: one row per captured page, with its sheet details and the answers to
  the questions on it.
- Tables: one row per table row with anything filled in, repeating the sheet it
  came from and the sheet's details, so each row can be analysed on its own.

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
SHEET_COLUMNS = ("sheet_id", "sheet_file", "form_version", "page", "captured_at")
ROW_COLUMN = "row"
# Excel only reads a CSV file as UTF-8 when it starts with a byte order mark.
CSV_ENCODING = "utf-8-sig"


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

    @property
    def sheet_count(self) -> int:
        return len(self.sheets)


def saved_sheet_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """How many checked and saved sheets each form has, by form ID."""
    counts: dict[str, int] = {}
    for capture in list_captures(connection):
        if capture.status == CAPTURE_STATUSES.SAVED and capture.form_id:
            counts[capture.form_id] = counts.get(capture.form_id, 0) + 1
    return counts


def collect(connection: sqlite3.Connection, form: Form) -> FormData:
    """Gather the checked sheets of ``form`` (its latest version), all versions."""
    captures = [
        capture
        for capture in list_captures(connection)
        if capture.status == CAPTURE_STATUSES.SAVED and capture.form_id == form.form_id
    ]
    versions: dict[int, Form] = {form.version: form}
    for capture in captures:
        version = capture.form_version
        if version is not None and version not in versions:
            loaded = load_form_version(connection, form.form_id, version)
            if loaded is not None:
                versions[version] = loaded
    ordered = [versions[number] for number in sorted(versions, reverse=True)]
    detail_columns, question_columns, table_columns = _columns(ordered)

    sheets: list[dict[str, str]] = []
    tables = {
        name: TableData(name, [*SHEET_COLUMNS, ROW_COLUMN, *detail_columns, *columns])
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
            for number, values in rows:
                tables[name].rows.append(
                    {
                        **sheet["meta"],
                        ROW_COLUMN: str(number),
                        **_flat(sheet["details"]),
                        **_flat(values),
                    }
                )
        documents.append(document)
    return FormData(
        form=form,
        sheet_columns=[*SHEET_COLUMNS, *detail_columns, *question_columns],
        sheets=sheets,
        tables=list(tables.values()),
        document={
            "form": {"id": form.form_id, "name": form.name},
            "exportedAt": datetime.now(UTC).isoformat(timespec="seconds"),
            "sheets": documents,
        },
    )


def write_csv(data: FormData, folder: Path) -> list[Path]:
    """Write the sheets file and one file per table into ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    base = safe_file_name(data.form.name)
    written = [folder / f"{base} - sheets.csv"]
    _write_rows(written[0], data.sheet_columns, data.sheets)
    for table in data.tables:
        path = folder / f"{base} - {safe_file_name(table.name)}.csv"
        _write_rows(path, table.columns, table.rows)
        written.append(path)
    return written


def write_json(data: FormData, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data.document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def safe_file_name(name: str) -> str:
    """A name made safe to use in a file name on any system."""
    return re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .-") or "data"


def _write_rows(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding=CSV_ENCODING) as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


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
    meta = {
        "sheet_id": capture.capture_id,
        "sheet_file": capture.original_name,
        "form_version": str(capture.form_version),
        "page": str(capture.page),
        "captured_at": capture.added_at,
    }
    details: dict[str, Any] = {}
    answers: dict[str, Any] = {}
    tables: dict[str, dict[int, dict[str, Any]]] = {}
    for answer in capture.answers:
        if not 0 <= answer.block_index < len(form.blocks):
            continue
        content = form.blocks[answer.block_index].content
        if isinstance(content, SheetDetails) and answer.column is not None:
            column = content.fields[answer.column]
            details[column.name] = _value(column.answer, answer.values)
        elif isinstance(content, Question):
            answers[content.name] = _value(content.answer, answer.values)
        elif (
            isinstance(content, TableBlock)
            and answer.column is not None
            and answer.table_row is not None
        ):
            column = content.columns[answer.column]
            row = tables.setdefault(content.name, {}).setdefault(answer.table_row, {})
            row[column.name] = _value(column.answer, answer.values)
    filled = {
        name: [
            (number + 1, values)
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
        "tables": {
            name: [{"row": number, "values": values} for number, values in rows]
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
