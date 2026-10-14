"""Round trip: lay out a form, draw it filled in, photograph it badly, scan it."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import cv2
import numpy as np
import pytest
from PySide6.QtGui import QColor

from omr_data_collector.constants import ANSWER_TYPES
from omr_data_collector.engine.scanning import (
    ScanError,
    read_sheet_identity,
    scan_sheet,
)
from omr_data_collector.layout.form_layout import layout_form
from omr_data_collector.layout.markers import marker_centres_mm
from omr_data_collector.layout.omr_template import (
    PageTemplate,
    page_template,
    with_writing_areas,
)
from omr_data_collector.models.AnswerSpec import AnswerSpec
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.Question import Question
from omr_data_collector.models.SheetDetails import SheetDetails
from omr_data_collector.rendering.page_photo import FILL_RADIUS_MM
from omr_data_collector.storage.form_store import (
    load_printed_layout,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from omr_data_collector.layout.form_layout import (
        FormLayout,
    )
    from omr_data_collector.models.Organization import Organization

from tests import sheets
from tests.sheets import LETTER, Sheet, intake_form

pytestmark = pytest.mark.usefixtures("qapp")


def answers_by_place(page) -> dict[tuple, tuple[str, ...]]:
    return {
        (answer.block_index, answer.table_row, answer.column): answer.values
        for answer in page.answers
    }


def test_a_filled_in_photo_reads_back_its_answers(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    form, layout = printed_form
    sheet = Sheet(form, organization, layout)
    # Question 0 (yes/no) is left empty.
    sheet.fill_question(1, 0, 3)
    sheet.fill_cell(2, row=0, column=1, choice=0)
    sheet.fill_cell(2, row=0, column=2, choice=2)
    sheet.fill_cell(2, row=2, column=2, choice=0)
    photo = sheet.photograph(tmp_path / "photo.jpg")

    page = scan_sheet(connection, photo, LETTER)

    assert page.identity.form_id == form.form_id
    assert page.identity.form_version == form.version
    assert page.identity.page == 1
    answers = answers_by_place(page)
    assert answers[0, None, None] == ("no",)
    assert answers[1, None, None] == ("food", "other")
    assert answers[2, 0, 1] == ("y",)
    assert answers[2, 0, 2] == ("referral",)
    assert answers[2, 2, 1] == ("n",)
    assert answers[2, 2, 2] == ("food",)
    assert answers[2, 1, 2] == ()
    assert all(not answer.problem for answer in page.answers)


def test_two_marks_where_one_is_allowed_are_flagged(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    form, layout = printed_form
    sheet = Sheet(form, organization, layout)
    sheet.fill_question(0, 0)
    sheet.fill_cell(2, row=1, column=2, choice=0)
    sheet.fill_cell(2, row=1, column=2, choice=1)
    photo = sheet.photograph(tmp_path / "photo.jpg")

    page = scan_sheet(connection, photo, LETTER)

    answers = {(a.block_index, a.table_row, a.column): a for a in page.answers}
    assert answers[0, None, None].values == ("yes",)
    assert not answers[0, None, None].problem
    service = answers[2, 1, 2]
    assert service.values == ("food", "clothing")
    assert "More than one" in service.problem


def test_light_marks_in_uneven_light_read_and_blank_answers_stay_blank(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    # Light pencil on a page lit from the left: page-wide, its empty bubbles on
    # the right are as dark as its marks on the left.
    form, layout = printed_form
    sheet = Sheet(form, organization, layout)
    sheet.use_mark(QColor("#6a6a6a"))
    sheet.fill_question(1, 1)
    sheet.fill_cell(2, row=0, column=2, choice=0)
    sheet.fill_cell(2, row=3, column=1, choice=0)
    photo = sheet.photograph(tmp_path / "photo.jpg", dim_right=0.4)

    page = scan_sheet(connection, photo, LETTER)

    answers = answers_by_place(page)
    assert answers[0, None, None] == ("no",)
    assert answers[1, None, None] == ("clothing",)
    assert answers[2, 0, 2] == ("food",)
    assert answers[2, 3, 1] == ("y",)
    for row in (1, 2, 4, 5):
        assert answers[2, row, 1] == ("n",)
        assert answers[2, row, 2] == ()
    assert all(not answer.problem for answer in page.answers)


def test_a_half_filled_bubble_reads_as_marked(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    form, layout = printed_form
    sheet = Sheet(form, organization, layout)
    sheet.fill_cell(2, row=1, column=2, choice=1, radius_mm=1.1)
    photo = sheet.photograph(tmp_path / "photo.jpg")

    page = scan_sheet(connection, photo, LETTER)

    assert answers_by_place(page)[2, 1, 2] == ("clothing",)


@pytest.mark.parametrize(
    ("radius_mm", "colour"),
    [(0.6, "black"), (FILL_RADIUS_MM, "#969696")],
    ids=["small dot", "faint pencil"],
)
def test_a_mark_that_cant_be_told_is_left_for_a_person(  # noqa: PLR0913 (fixtures)
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
    radius_mm: float,
    colour: str,
) -> None:
    form, layout = printed_form
    sheet = Sheet(form, organization, layout)
    sheet.fill_cell(2, row=0, column=2, choice=0)
    sheet.use_mark(QColor(colour))
    sheet.fill_cell(2, row=4, column=2, choice=2, radius_mm=radius_mm)
    photo = sheet.photograph(tmp_path / "photo.jpg")

    page = scan_sheet(connection, photo, LETTER)

    answers = {(a.block_index, a.table_row, a.column): a for a in page.answers}
    unclear = answers[2, 4, 2]
    assert unclear.values == ()
    assert "Couldn't tell" in unclear.problem
    assert answers[2, 0, 2].values == ("food",)
    assert not answers[2, 0, 2].problem


def test_a_page_of_marks_that_cant_be_told_isnt_read(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    form, layout = printed_form
    sheet = Sheet(form, organization, layout)
    sheet.use_mark(QColor("#969696"))
    for row in range(6):
        sheet.fill_cell(2, row=row, column=2, choice=row % 3)
    photo = sheet.photograph(tmp_path / "photo.jpg")

    with pytest.raises(ScanError, match="marked bubbles from the empty ones"):
        scan_sheet(connection, photo, LETTER)


def test_a_missing_corner_marker_is_reported(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    form, layout = printed_form
    sheet = Sheet(form, organization, layout)
    sheet.cover_marker(3)
    photo = sheet.photograph(tmp_path / "photo.jpg")

    with pytest.raises(ScanError, match="corner markers"):
        scan_sheet(connection, photo, LETTER)


def test_a_picture_without_our_qr_code_is_reported() -> None:
    blank = np.full((400, 300), 255, dtype=np.uint8)

    with pytest.raises(ScanError, match="QR code"):
        read_sheet_identity(blank)


def test_a_sheet_from_an_unknown_form_is_reported(
    connection: sqlite3.Connection, organization: Organization, tmp_path: Path
) -> None:
    form = intake_form()  # never saved here
    sheet = Sheet(form, organization, layout_form(form, LETTER))
    photo = sheet.photograph(tmp_path / "photo.jpg")

    with pytest.raises(ScanError, match="isn't on this computer"):
        scan_sheet(connection, photo, LETTER)


def test_printing_stores_every_pages_template(
    connection: sqlite3.Connection, printed_form: tuple[Form, FormLayout]
) -> None:
    form, layout = printed_form

    stored = load_printed_layout(connection, form.form_id, form.version)

    assert stored is not None
    (page,) = stored["pages"]
    assert PageTemplate.from_dict(page) == page_template(layout, layout.pages[0])


def test_the_template_has_a_field_per_question_row_and_table_cell() -> None:
    form = intake_form()
    layout = layout_form(form, LETTER)

    template = page_template(layout, layout.pages[0])

    assert set(template.fields) == {
        "q0r0",
        "q1r0",
        *(f"t2c{column}r{row}" for column in (1, 2) for row in range(6)),
    }
    blocks = template.template["fieldBlocks"]
    assert blocks["q1r0"]["fieldLabels"] == ["q1r0"]
    assert blocks["t2c2p0"]["fieldLabels"] == [f"t2c2r{row}" for row in range(6)]
    # The straightened page runs from the top-left marker's centre to the
    # bottom-right one's.
    (left, top), _, (right, bottom), _ = marker_centres_mm(
        layout.paper_width_mm, layout.paper_height_mm
    )
    assert template.template["templateDimensions"] == [
        round((right - left) * 6),
        round((bottom - top) * 6),
    ]


def test_bubbles_carry_the_answers_real_values(
    printed_form: tuple[Form, FormLayout],
) -> None:
    _, layout = printed_form

    template = page_template(layout, layout.pages[0])

    types = template.template["customBubbleFieldTypes"]
    assert types["CUSTOM_q1r0"]["bubbleValues"] == [
        "food",
        "clothing",
        "referral",
        "other",
    ]
    assert types["CUSTOM_q0r0"]["bubbleValues"] == ["yes"]
    services = next(r for r in template.regions if r.key == (1, None, None))
    assert len(services.bubbles) == 4


def test_a_low_resolution_photo_still_reads(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """About 1000 pixels across the page, as from an older phone."""
    monkeypatch.setattr(sheets, "PIXELS_PER_MM", 4)
    form, layout = printed_form
    sheet = sheets.Sheet(form, organization, layout)
    sheet.fill_question(1, 0, 3)
    photo = sheet.photograph(tmp_path / "small.jpg", degrees=4)

    page = scan_sheet(connection, photo, LETTER)

    answers = {answer.block_index: answer.values for answer in page.answers}
    assert answers[1] == ("food", "other")


@pytest.mark.parametrize(
    "blur_and_turn",
    [(1.2, 3), (1.2, 8)],
    ids=["out of focus", "out of focus and turned"],
)
def test_a_soft_photos_qr_code_still_reads(
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    blur_and_turn: tuple[float, float],
) -> None:
    """Slightly out of focus, about 1100 pixels across: what zbar couldn't read."""
    monkeypatch.setattr(sheets, "PIXELS_PER_MM", 5)
    blur, turn = blur_and_turn
    form, layout = printed_form
    photo = sheets.Sheet(form, organization, layout).photograph(
        tmp_path / "soft.jpg", degrees=turn
    )
    image = cv2.imread(str(photo))
    assert image is not None
    image = cv2.GaussianBlur(image, (0, 0), blur)

    identity = read_sheet_identity(image)

    assert identity.form_id == form.form_id
    assert identity.page == 1


def test_an_unreadable_full_size_photo_is_given_up_on_quickly(
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 12-megapixel phone photo too blurred to read: once took over ten minutes."""
    monkeypatch.setattr(sheets, "PIXELS_PER_MM", 16)
    form, layout = printed_form
    photo = sheets.Sheet(form, organization, layout).photograph(tmp_path / "big.jpg")
    image = cv2.imread(str(photo))
    assert image is not None
    image = cv2.GaussianBlur(image, (0, 0), 12)

    started = time.perf_counter()
    with pytest.raises(ScanError, match="QR code"):
        read_sheet_identity(image)

    assert time.perf_counter() - started < 30


def test_a_photo_taken_at_a_tilt_still_reads(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    """The top of the page 15% narrower than the bottom, as from a phone held at a slant.

    The same tilt failed a real photo in another OMRChecker-based app, whose
    corner markers were matched at one size for the whole page; OMRChecker v2
    sizes each corner's marker on its own.
    """
    form, layout = printed_form
    sheet = Sheet(form, organization, layout)
    sheet.fill_question(1, 0, 3)
    sheet.fill_cell(2, row=2, column=2, choice=0)
    photo = sheet.photograph(tmp_path / "flat.jpg")
    image = cv2.imread(str(photo))
    assert image is not None
    height, width = image.shape[:2]
    inset = width * 0.15 / 2
    corners = np.array(
        [[0, 0], [width, 0], [0, height], [width, height]], dtype=np.float32
    )
    slanted = np.array(
        [[inset, 0], [width - inset, 0], [0, height], [width, height]],
        dtype=np.float32,
    )
    image = cv2.warpPerspective(
        image,
        cv2.getPerspectiveTransform(corners, slanted),
        (width, height),
        borderValue=(112, 112, 112),
    )
    tilted = tmp_path / "tilted.jpg"
    cv2.imwrite(str(tilted), image)

    page = scan_sheet(connection, tilted, LETTER)

    answers = answers_by_place(page)
    assert answers[1, None, None] == ("food", "other")
    assert answers[2, 2, 2] == ("food",)
    assert all(not answer.problem for answer in page.answers)


def written_form() -> Form:
    return Form(
        name="Shift log",
        blocks=(
            FormBlock(SheetDetails(name="Sheet details")),
            FormBlock(
                Question(
                    "notes",
                    "Anything to note about the shift?",
                    answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=30),
                )
            ),
        ),
    )


def test_typing_goes_where_the_answer_is_written_not_on_its_label() -> None:
    form = written_form()
    layout = layout_form(form, LETTER)
    template = page_template(layout, layout.pages[0])

    manager = next(r for r in template.regions if r.key == (0, None, 2))
    assert manager.writing is not None
    x, y, width, height = manager.writing
    # After the "Manager:" label, to the end of the field, on its line.
    assert x > manager.rect[0]
    assert x + width == pytest.approx(manager.rect[0] + manager.rect[2], abs=1)
    assert (y, height) == (manager.rect[1], manager.rect[3])
    assert manager.entry_rect == manager.writing

    notes = next(r for r in template.regions if r.key == (1, None, None))
    assert notes.writing is not None
    # The answer's row, below the prompt.
    assert notes.writing[1] > notes.rect[1]
    assert notes.writing[1] + notes.writing[3] <= notes.rect[1] + notes.rect[3] + 1

    # Kept with the printed page.
    assert PageTemplate.from_dict(template.to_dict()).regions == template.regions


def test_pages_printed_before_writing_areas_get_them_where_the_layout_matches() -> None:
    form = written_form()
    layout = layout_form(form, LETTER)
    fresh = page_template(layout, layout.pages[0])
    stored = fresh.to_dict()
    for region in stored["regions"]:
        del region["writing"]
    stored["regions"][1]["rect"][0] += 5  # Laid out differently since printing.
    old = PageTemplate.from_dict(stored)
    assert all(region.writing is None for region in old.regions)

    filled = with_writing_areas(old, fresh)

    assert filled.regions[0].writing == fresh.regions[0].writing
    assert filled.regions[1].writing is None
