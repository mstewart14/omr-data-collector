"""Answers on paper only: printed, but not entered or exported (wiki 60016)."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from omr_data_collector.constants import ANSWER_TYPES, WRITTEN_DATA_TYPES
from omr_data_collector.export.data_export import collect
from omr_data_collector.models.answer_keys import not_entered
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.SheetDetails import SheetDetails
from omr_data_collector.models.TableBlock import TableBlock
from omr_data_collector.storage.capture_store import list_captures
from omr_data_collector.storage.form_store import save_form
from omr_data_collector.ui.CapturePage import CapturePage
from omr_data_collector.ui.QuestionsPage import QuestionsPage
from tests.test_capture import cell_text
from tests.test_export import SHEET_ONE, add_sheet, saved_form

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from pytestqt.qtbot import QtBot

pytestmark = pytest.mark.usefixtures("qapp")

WRITTEN = AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=10)


def test_not_entered_is_kept_and_only_stored_when_set() -> None:
    paper_only = replace(WRITTEN, entered=False)

    assert "entered" not in WRITTEN.to_dict()
    assert paper_only.to_dict()["entered"] is False
    assert AnswerSpec.from_dict(paper_only.to_dict()) == paper_only
    assert AnswerSpec.from_dict(WRITTEN.to_dict()).entered
    assert not paper_only.is_entered
    # Only written answers can be on paper only: bubbles are always read.
    yes_no = AnswerSpec(
        ANSWER_TYPES.YES_NO, choices=(Choice("Y"), Choice("N")), entered=False
    )
    assert yes_no.is_entered


def paper_only(form: Form) -> Form:
    """``form`` with its Date field and Visits' time column on paper only."""
    blocks = []
    for block in form.blocks:
        content = block.content
        if isinstance(content, SheetDetails):
            date, *others = content.fields
            not_typed = replace(date.answer, entered=False)
            content = replace(
                content, fields=(replace(date, answer=not_typed), *others)
            )
        elif isinstance(content, TableBlock):
            time, *others = content.columns
            not_typed = replace(time.answer, entered=False)
            content = replace(
                content, columns=(replace(time, answer=not_typed), *others)
            )
        blocks.append(FormBlock(content))
    return replace(form, blocks=tuple(blocks))


@pytest.fixture
def forms(connection: sqlite3.Connection, tmp_path: Path) -> tuple[Form, Form]:
    """A printed form with a checked sheet, and the version after it on paper only."""
    printed = saved_form(connection)
    add_sheet(connection, tmp_path, printed, "one.jpg", SHEET_ONE)
    # The first version was printed, so this saves a second.
    latest = save_form(connection, paper_only(printed))
    assert latest.version == printed.version + 1
    return printed, latest


def test_the_latest_version_decides_whats_entered(forms: tuple[Form, Form]) -> None:
    printed, latest = forms

    assert not_entered([latest, printed]) == {
        ("details", None, "Date"),
        ("table", "Visits", "time"),
    }
    assert not_entered([printed]) == set()


def test_answers_not_entered_arent_exported_from_any_version(
    connection: sqlite3.Connection, forms: tuple[Form, Form]
) -> None:
    _, latest = forms

    data = collect(connection, latest)

    assert "Date" not in data.sheet_columns
    assert "Shift" in data.sheet_columns
    (visits,) = data.tables
    assert "time" not in visits.columns
    assert "Date" not in visits.columns
    assert [(row["row"], row["first"]) for row in visits.rows] == [("1", "yes")]
    (sheet,) = data.document["sheets"]
    assert "Date" not in sheet["details"]
    assert all("time" not in row["values"] for row in sheet["tables"]["Visits"])
    assert data.missing == []


def test_a_table_with_every_column_not_entered_isnt_exported(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    printed = saved_form(connection)
    add_sheet(connection, tmp_path, printed, "one.jpg", SHEET_ONE)
    blocks = [
        block
        if not isinstance(block.content, TableBlock)
        else FormBlock(
            replace(
                block.content,
                columns=tuple(
                    replace(
                        column,
                        answer=replace(
                            column.answer,
                            answer_type=ANSWER_TYPES.WRITTEN,
                            entered=False,
                        ),
                    )
                    for column in block.content.columns
                ),
            )
        )
        for block in printed.blocks
    ]
    latest = save_form(connection, replace(printed, blocks=tuple(blocks)))

    assert collect(connection, latest).tables == []


@pytest.mark.usefixtures("forms")
def test_capture_leaves_answers_not_entered_out_but_keeps_them(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = CapturePage(connection)
    qtbot.addWidget(page)
    (capture,) = list_captures(connection)

    # The sheet was printed from the first version: the latest one decides.
    assert len(page._answers) == len(capture.answers) - 4  # noqa: SLF001 (Date, 3 times)
    names = [cell_text(page, row, 0) for row in range(page.answers_table.rowCount())]
    assert "Shift" in names
    assert not any("Date" in name or "time" in name for name in names)
    assert not page.has_unsaved_changes()

    assert page.save_data()

    (saved,) = list_captures(connection)
    # What was stored for them stays, untouched.
    assert saved.answers == capture.answers


def test_a_written_answer_can_be_set_as_not_entered(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = QuestionsPage(connection)
    qtbot.addWidget(page)
    page.show()
    fields = page.answer_fields
    check = fields.not_entered_check

    fields.set_spec(AnswerSpec.default(ANSWER_TYPES.YES_NO))
    assert not check.isVisibleTo(page)
    fields.set_spec(replace(WRITTEN, data_type=WRITTEN_DATA_TYPES.NUMBER))
    assert check.isVisibleTo(page)
    assert not check.isChecked()

    check.setChecked(True)

    assert fields.spec().entered is False
    assert check.text() == "Skip w&hen entering data (on paper only)"
    assert "left out of exported data" in check.accessibleDescription()
