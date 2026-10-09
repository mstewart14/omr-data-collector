"""Sheet details: labelled answers along a line, like Date, Shift and Staff."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt

from omr_data_collector.constants import (
    ANSWER_TYPES,
    BLOCK_KINDS,
    PAPER_SIZES,
    WRITTEN_DATA_TYPES,
)
from omr_data_collector.engine.reading import read_capture
from omr_data_collector.layout.form_layout import (
    ANSWER_ROW_HEIGHT_MM,
    details_geometry,
    layout_form,
)
from omr_data_collector.layout.omr_template import page_template, printed_layout
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.SheetDetails import SheetDetails
from omr_data_collector.models.TableBlock import Column
from omr_data_collector.storage.capture_store import add_capture
from omr_data_collector.storage.form_store import mark_printed, save_form
from omr_data_collector.ui.ColumnDialog import ColumnDialog
from omr_data_collector.ui.FormsPage import FormsPage
from omr_data_collector.ui.SheetDetailsDialog import SheetDetailsDialog
from tests.sheets import Sheet

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

    from omr_data_collector.models.Organization import Organization

pytestmark = pytest.mark.usefixtures("qapp")

LETTER = PAPER_SIZES.LETTER
SHIFT = Column(
    "Shift",
    answer=AnswerSpec(
        ANSWER_TYPES.ONE_CHOICE,
        choices=(
            Choice("Day", "day"),
            Choice("Evening", "evening"),
            Choice("Night", "night"),
        ),
    ),
)


def details(*fields: Column) -> SheetDetails:
    return SheetDetails(name="Sheet details", fields=fields).normalized()


def test_new_sheet_details_start_with_the_usual_fields() -> None:
    starter = SheetDetails(name="Sheet details")

    assert [field.name for field in starter.fields] == [
        "Date",
        "Shift",
        "Manager",
        "Supervisor",
        "Staff",
    ]
    date = starter.fields[0].answer
    assert date.data_type == WRITTEN_DATA_TYPES.DATE_TIME
    assert starter.normalized().validation_errors(set()) == {}


def test_sheet_details_are_stored_with_the_form() -> None:
    form = Form(name="Log", blocks=(FormBlock(details(SHIFT)),))

    stored = Form.from_definition(form.definition(), form_id=form.form_id, version=1)

    (block,) = stored.blocks
    assert block.kind == BLOCK_KINDS.SHEET_DETAILS
    assert block.content == form.blocks[0].content


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ((), "Add at least one field."),
        (
            (Column("Staff", answer=AnswerSpec(ANSWER_TYPES.WRITTEN)),) * 2,
            'Field 2 ("Staff"): These sheet details already have a field called '
            '"Staff".',
        ),
    ],
)
def test_sheet_details_need_distinct_fields(
    fields: tuple[Column, ...], message: str
) -> None:
    assert details(*fields).validation_errors(set()) == {"fields": message}


def test_fields_run_along_a_line_and_wrap() -> None:
    starter = SheetDetails(name="Sheet details").normalized()

    wide = details_geometry(starter, width_mm=400)
    narrow = details_geometry(starter, width_mm=120)

    assert {field.y_mm for field in wide.fields} == {0}
    assert wide.height_mm == ANSWER_ROW_HEIGHT_MM
    assert len({field.y_mm for field in narrow.fields}) > 1
    assert all(f.x_mm + f.width_mm <= 120 for f in narrow.fields)
    # The date is boxes, with its slashes printed; the rest are lines to write on.
    date = wide.fields[0]
    assert "".join(box.printed or "_" for box in date.boxes) == "____/__/__"
    assert all(field.lines and not field.boxes for field in wide.fields[1:])


def test_choices_get_bubbles_read_as_one_field() -> None:
    form = Form(name="Log", blocks=(FormBlock(details(SHIFT)),))
    layout = layout_form(form, LETTER)

    template = page_template(layout, layout.pages[0])

    assert set(template.fields) == {"d0f0"}
    assert template.fields["d0f0"].column == 0
    assert [region.key for region in template.regions] == [(0, None, 0)]


def test_a_filled_in_shift_is_read_from_the_photo(
    connection: sqlite3.Connection, organization: Organization, tmp_path: Path
) -> None:
    starter = SheetDetails(name="Sheet details").fields
    form = save_form(
        connection,
        Form(name="Shift log", blocks=(FormBlock(details(starter[0], SHIFT)),)),
    )
    layout = layout_form(form, LETTER)
    mark_printed(connection, form.form_id, form.version, printed_layout(layout))
    sheet = Sheet(form, organization, layout)
    sheet.fill_detail(0, field=1, choice=1)
    photo = sheet.photograph(tmp_path / "shift.jpg")

    capture = read_capture(connection, add_capture(connection, photo), LETTER)

    shift = capture.answer((0, None, 1))
    date = capture.answer((0, None, 0))
    assert shift is not None
    assert shift.values == ("evening",)
    assert date is not None
    assert date.values == ()  # handwritten, typed in when checking


# --- Editing ---------------------------------------------------------------------------


def test_the_palette_adds_a_fresh_set_to_change(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = FormsPage(connection)
    qtbot.addWidget(page)
    messages: list[str] = []
    page.status_message.connect(messages.append)
    page.refresh_palette()
    starter = page.block_palette.lists[BLOCK_KINDS.SHEET_DETAILS].item(0)

    page.add_library_block(
        BLOCK_KINDS.SHEET_DETAILS, starter.data(Qt.ItemDataRole.UserRole), None
    )

    (block,) = page._blocks  # noqa: SLF001 (the form being edited)
    assert block.kind == BLOCK_KINDS.SHEET_DETAILS
    assert block.source_id is None
    assert isinstance(block.content, SheetDetails)
    assert len(block.content.fields) == 5
    assert messages == [
        'Added "Sheet details" to the form. Edit block changes its fields.'
    ]
    assert page.edit_block_button.isEnabled()
    page.revert()


def test_the_dialog_adds_reorders_and_removes_fields(
    qtbot: QtBot, mocker: MockerFixture
) -> None:
    dialog = SheetDetailsDialog(None, details(SHIFT))
    qtbot.addWidget(dialog)
    staff = Column("Staff", answer=AnswerSpec(ANSWER_TYPES.WRITTEN))
    edit = mocker.patch(
        "omr_data_collector.ui.SheetDetailsDialog.edit_field", return_value=staff
    )

    dialog.add_field()
    dialog.move_selected_field(-1)
    dialog.accept()

    edit.assert_called_once_with(dialog, None, {"Shift"})
    accepted = dialog.details()
    assert accepted is not None
    assert [field.name for field in accepted.fields] == ["Staff", "Shift"]


def test_the_dialog_wont_accept_no_fields(qtbot: QtBot) -> None:
    dialog = SheetDetailsDialog(None, details(SHIFT))
    qtbot.addWidget(dialog)

    dialog.remove_selected_field()
    dialog.accept()

    assert dialog.details() is None
    assert dialog.error_labels["fields"].text() == "Add at least one field."


def test_a_field_is_set_up_like_a_column_without_an_example(qtbot: QtBot) -> None:
    dialog = ColumnDialog(None, None, {"Date"}, sheet_detail=True)
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "Add field"
    assert not dialog.form.isRowVisible(dialog.example_edit)
    dialog.name_edit.setText("date")
    dialog.accept()

    assert dialog.column() is None
    assert dialog.error_labels["name"].text() == (
        'These sheet details already have a field called "date".'
    )
