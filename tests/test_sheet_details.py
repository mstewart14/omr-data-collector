"""Sheet details: labelled answers along a line, like Date, Shift and Staff."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from omr_data_collector.constants import (
    ANSWER_TYPES,
    BLOCK_KINDS,
    PAGE_ORIENTATIONS,
    PAPER_SIZES,
    SHEET_DETAILS_PLACEMENTS,
    WRITTEN_DATA_TYPES,
)
from omr_data_collector.engine.reading import read_capture
from omr_data_collector.layout.form_layout import (
    ANSWER_ROW_HEIGHT_MM,
    HEADER_DETAIL_ROW_MM,
    HEADER_HEIGHT_MM,
    HEADER_TEXT_GAP_MM,
    QR_SIZE_MM,
    details_geometry,
    layout_form,
)
from omr_data_collector.layout.frozen_layout import printed_layout
from omr_data_collector.layout.omr_template import page_template
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.SheetDetails import SheetDetails
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.storage.capture_store import add_capture
from omr_data_collector.storage.form_store import mark_printed, save_form
from omr_data_collector.ui.ColumnDialog import ColumnDialog
from omr_data_collector.ui.FormsPage import NO_SHEET_DETAILS, FormsPage
from omr_data_collector.ui.PageCanvas import PageCanvas
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


def details(
    *fields: Column, placement: str = SHEET_DETAILS_PLACEMENTS.HEADER
) -> SheetDetails:
    return SheetDetails(
        name="Sheet details", fields=fields, placement=placement
    ).normalized()


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


def test_sheet_details_arent_added_from_the_palette(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = FormsPage(connection)
    qtbot.addWidget(page)

    page.refresh_palette()

    assert BLOCK_KINDS.SHEET_DETAILS not in page.block_palette.lists


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


# --- In the header (the default) ---------------------------------------------------


def long_form(*blocks: FormBlock) -> Form:
    """Sheet details, then a table long enough for two pages."""
    table = TableBlock(
        "Visits",
        rows=50,
        columns=(Column("time", answer=AnswerSpec(ANSWER_TYPES.WRITTEN)),),
    )
    return Form(name="Log", blocks=(*blocks, FormBlock(table)))


def test_header_details_stack_beside_the_qr_code_on_every_page() -> None:
    form = long_form(FormBlock(SheetDetails(name="Sheet details").normalized()))

    layout = layout_form(form, LETTER)

    assert len(layout.pages) == 2
    for page in layout.pages:
        header, *_ = page.blocks
        assert header.in_header
        assert header.y_mm == 0
        assert header.details is not None
        assert [f.y_mm for f in header.details.fields] == [
            n * HEADER_DETAIL_ROW_MM for n in range(5)
        ]
        assert header.x_mm + (header.width_mm or 0) == pytest.approx(
            layout.width_mm - QR_SIZE_MM - HEADER_TEXT_GAP_MM
        )
    # Five fields need a taller header, and the names get less room.
    assert layout.header_height_mm > HEADER_HEIGHT_MM
    assert layout.header_text_width_mm < layout.width_mm - QR_SIZE_MM
    first_table = layout.pages[0].blocks[1]
    assert first_table.y_mm >= layout.header_height_mm
    assert layout.warnings == ()


def test_a_few_header_details_keep_the_usual_header() -> None:
    starter = SheetDetails(name="Sheet details").fields
    form = long_form(FormBlock(details(starter[0], starter[1], starter[2])))

    assert layout_form(form, LETTER).header_height_mm == HEADER_HEIGHT_MM


def test_header_details_too_wide_are_reported() -> None:
    wide = Column(
        "Program",
        answer=AnswerSpec(
            ANSWER_TYPES.ONE_CHOICE,
            choices=tuple(Choice(f"Program {n}", str(n)) for n in range(6)),
        ),
    )

    layout = layout_form(long_form(FormBlock(details(wide))), LETTER)

    (warning,) = layout.warnings
    assert warning.startswith('The sheet details "Sheet details" are ')
    assert "put them along a line" in warning


def test_only_one_set_of_details_fits_in_the_header() -> None:
    form = Form(
        name="Log",
        blocks=(FormBlock(details(SHIFT)), FormBlock(details(SHIFT))),
    )

    assert form.validation_errors(set())["blocks"] == (
        "Blocks 1 and 2 are both sheet details in the header, which has room "
        "for one; put one along a line instead."
    )


def test_details_stored_before_placement_existed_stay_along_a_line() -> None:
    data = details(SHIFT).to_dict()
    del data["placement"]

    assert SheetDetails.from_dict(data).placement == SHEET_DETAILS_PLACEMENTS.LINE


def test_every_page_reads_the_header_details() -> None:
    form = long_form(FormBlock(details(SHIFT)))
    layout = layout_form(form, LETTER)

    templates = [page_template(layout, page) for page in layout.pages]

    for template in templates:
        assert template.fields["d0f0"].column == 0
        assert template.regions[0].key == (0, None, 0)


def test_dropping_a_block_on_the_header_doesnt_place_it_there(qtbot: QtBot) -> None:
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 1200)
    form = long_form(FormBlock(details(SHIFT)))
    canvas.set_form(form, None, LETTER)
    header = next(area for area in canvas._areas if area.in_header)  # noqa: SLF001

    assert canvas.block_at(header.rect.center()) == 0
    assert canvas.insert_index_at(header.rect.center()) == 1


def make_forms_page(qtbot: QtBot, connection: sqlite3.Connection) -> FormsPage:
    page = FormsPage(connection)
    qtbot.addWidget(page)
    return page


def choose_placement(page: FormsPage, placement: str) -> None:
    page.sheet_details_combo.setCurrentIndex(
        page.sheet_details_combo.findData(placement)
    )


def details_blocks(page: FormsPage) -> list[SheetDetails]:
    return [
        block.content
        for block in page._blocks  # noqa: SLF001 (the form being edited)
        if isinstance(block.content, SheetDetails)
    ]


def test_form_details_add_move_and_remove_the_sheet_details(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_forms_page(qtbot, connection)
    assert page.sheet_details_combo.currentData() == NO_SHEET_DETAILS
    assert not page.edit_details_button.isEnabled()

    choose_placement(page, SHEET_DETAILS_PLACEMENTS.HEADER)

    (added,) = details_blocks(page)
    assert added.placement == SHEET_DETAILS_PLACEMENTS.HEADER
    assert [field.name for field in added.fields][:2] == ["Date", "Shift"]
    assert page.edit_details_button.isEnabled()

    choose_placement(page, SHEET_DETAILS_PLACEMENTS.LINE)

    (moved,) = details_blocks(page)
    assert moved.placement == SHEET_DETAILS_PLACEMENTS.LINE
    assert moved.fields == added.fields

    choose_placement(page, NO_SHEET_DETAILS)

    assert details_blocks(page) == []

    page.undo()

    assert page.sheet_details_combo.currentData() == SHEET_DETAILS_PLACEMENTS.LINE
    page.revert()


def test_the_combo_follows_the_form_opened(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    form = save_form(
        connection,
        Form(
            name="Log",
            blocks=(
                FormBlock(details(SHIFT, placement=SHEET_DETAILS_PLACEMENTS.LINE)),
            ),
        ),
    )
    page = make_forms_page(qtbot, connection)

    assert page.open_item(form.form_id)

    assert page.sheet_details_combo.currentData() == SHEET_DETAILS_PLACEMENTS.LINE


def test_edit_sheet_details_opens_the_fields(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    page = make_forms_page(qtbot, connection)
    choose_placement(page, SHEET_DETAILS_PLACEMENTS.HEADER)
    (current,) = details_blocks(page)
    edited = replace(current, fields=(SHIFT,))
    write = mocker.patch(
        "omr_data_collector.ui.FormsPage.write_block", return_value=edited
    )

    page.edit_details_button.click()

    write.assert_called_once_with(
        page,
        BLOCK_KINDS.SHEET_DETAILS,
        current,
        (PAPER_SIZES.LETTER, PAGE_ORIENTATIONS.PORTRAIT),
    )
    assert details_blocks(page) == [edited]
    page.revert()


def test_the_header_keeps_one_set_when_another_moves_in(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_forms_page(qtbot, connection)
    page.load_fields(
        Form(
            name="Log",
            blocks=(
                FormBlock(details(SHIFT, placement=SHEET_DETAILS_PLACEMENTS.LINE)),
                FormBlock(details(SHIFT, placement=SHEET_DETAILS_PLACEMENTS.HEADER)),
            ),
        )
    )

    choose_placement(page, SHEET_DETAILS_PLACEMENTS.HEADER)

    first, second = details_blocks(page)
    assert first.placement == SHEET_DETAILS_PLACEMENTS.HEADER
    assert second.placement == SHEET_DETAILS_PLACEMENTS.LINE
    page.revert()
