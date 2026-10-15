"""Sheets photographed or printed the wrong way round, or at the wrong size."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import cv2
import numpy as np
import pytest

from omr_data_collector.constants import CAPTURE_STATUSES, PAGE_ORIENTATIONS
from omr_data_collector.engine.alignment import (
    PaperFrame,
    misalignment,
    quarter_turns,
    turn_upright,
)
from omr_data_collector.engine.scanning import ScanError, find_form_code, scan_sheet
from omr_data_collector.layout.form_layout import layout_form
from omr_data_collector.layout.omr_template import TEMPLATE_PX_PER_MM, printed_layout
from omr_data_collector.storage.capture_store import add_capture, list_captures
from omr_data_collector.storage.form_store import (
    load_printed_layout,
    mark_printed,
    save_form,
)
from omr_data_collector.ui.CapturePage import CapturePage
from tests.sheets import BORDER_MM, LETTER, PIXELS_PER_MM, Sheet, intake_form

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from omr_data_collector.layout.form_layout import FormLayout
    from omr_data_collector.models.Form import Form
    from omr_data_collector.models.Organization import Organization

GREY = (112, 112, 112)


def filled(
    form: Form, organization: Organization, layout: FormLayout, path: Path
) -> np.ndarray:
    """The intake sheet with Food and Other ticked and a table bubble, as a flat photo."""
    sheet = Sheet(form, organization, layout)
    sheet.fill_question(1, 0, 3)
    sheet.fill_cell(2, row=0, column=1, choice=0)
    image = cv2.imread(str(sheet.photograph(path, degrees=0)))
    assert image is not None
    return image


def save(image: np.ndarray, path: Path) -> Path:
    cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return path


def answers_of(
    connection: sqlite3.Connection, path: Path, *, reframe: bool = False
) -> dict:
    page = scan_sheet(connection, path, LETTER, reframe=reframe)
    return {
        (answer.block_index, answer.table_row, answer.column): answer.values
        for answer in page.answers
    }


def assert_read_right(answers: dict) -> None:
    assert answers[1, None, None] == ("food", "other")
    assert answers[2, 0, 1] == ("y",)


@pytest.mark.parametrize(
    "turn",
    [cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE],
)
def test_a_photo_taken_sideways_or_upside_down_reads_right(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
    turn: int,
) -> None:
    form, layout = printed_form
    image = filled(form, organization, layout, tmp_path / "flat.jpg")

    turned = save(cv2.rotate(image, turn), tmp_path / "turned.jpg")

    assert_read_right(answers_of(connection, turned))


def test_a_scan_with_no_background_reads(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    form, layout = printed_form
    image = filled(form, organization, layout, tmp_path / "flat.jpg")
    border = round(BORDER_MM * PIXELS_PER_MM)

    # The paper fills the whole picture, as on a flatbed scanner.
    scan = save(image[border:-border, border:-border], tmp_path / "scan.jpg")

    assert_read_right(answers_of(connection, scan))


@pytest.fixture
def shrunk_landscape(
    connection: sqlite3.Connection, organization: Organization, tmp_path: Path
) -> Path:
    """A landscape form printed shrunk to fit portrait paper, as a photo."""
    form = save_form(
        connection, replace(intake_form(), orientation=PAGE_ORIENTATIONS.LANDSCAPE)
    )
    layout = layout_form(form, LETTER)
    mark_printed(connection, form.form_id, form.version, printed_layout(layout))
    image = filled(form, organization, layout, tmp_path / "flat.jpg")
    border = round(BORDER_MM * PIXELS_PER_MM)
    paper = image[border:-border, border:-border]
    # Letter portrait: the landscape page's width shrinks to the paper's.
    width = round(215.9 * PIXELS_PER_MM)
    portrait = np.full((round(279.4 * PIXELS_PER_MM), width, 3), 255, np.uint8)
    small = cv2.resize(
        paper,
        (width, round(paper.shape[0] * width / paper.shape[1])),
        interpolation=cv2.INTER_AREA,
    )
    top = (portrait.shape[0] - small.shape[0]) // 2
    portrait[top : top + small.shape[0]] = small
    photo = cv2.copyMakeBorder(
        portrait, border, border, border, border, cv2.BORDER_CONSTANT, value=GREY
    )
    turn = cv2.getRotationMatrix2D((photo.shape[1] / 2, photo.shape[0] / 2), 2, 1)
    photo = cv2.warpAffine(
        photo, turn, (photo.shape[1], photo.shape[0]), borderValue=GREY
    )
    return save(photo, tmp_path / "shrunk.jpg")


def test_a_page_printed_at_another_size_is_refused_not_misread(
    connection: sqlite3.Connection, shrunk_landscape: Path
) -> None:
    with pytest.raises(ScanError, match="didn't line up with its form"):
        scan_sheet(connection, shrunk_landscape, LETTER)


def test_read_it_anyway_finds_the_page_from_its_qr_code(
    connection: sqlite3.Connection, shrunk_landscape: Path
) -> None:
    assert_read_right(answers_of(connection, shrunk_landscape, reframe=True))


def test_read_it_anyway_reads_a_well_printed_sheet_too(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    form, layout = printed_form
    filled(form, organization, layout, tmp_path / "flat.jpg")

    assert_read_right(answers_of(connection, tmp_path / "flat.jpg", reframe=True))


# --- The QR code's corners ----------------------------------------------------------


def test_the_code_says_which_way_up_the_picture_is(
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    form, layout = printed_form
    image = filled(form, organization, layout, tmp_path / "flat.jpg")
    upright = find_form_code(image).corners

    for turns, rotation in enumerate(
        (
            None,
            cv2.ROTATE_90_CLOCKWISE,
            cv2.ROTATE_180,
            cv2.ROTATE_90_COUNTERCLOCKWISE,
        )
    ):
        turned = image if rotation is None else cv2.rotate(image, rotation)
        corners = find_form_code(turned).corners

        assert quarter_turns(corners) == turns
        back, moved = turn_upright(turned, corners)
        assert back.shape == image.shape
        # The reader places corners to within a few pixels each time.
        assert np.allclose(moved, upright, atol=5)


def test_a_straightened_code_must_be_where_the_form_puts_it(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    form, layout = printed_form
    image = filled(form, organization, layout, tmp_path / "flat.jpg")
    identity = find_form_code(image).identity
    stored = load_printed_layout(connection, form.form_id, form.version)
    assert stored is not None
    expected = PaperFrame.from_template(
        stored["pages"][0]["template"]
    ).code_corners_template_px(identity)
    millimetre = TEMPLATE_PX_PER_MM

    assert misalignment(expected, expected) is None
    assert misalignment(expected + 4 * millimetre, expected) is None
    assert misalignment(None, expected) is not None
    assert "from where the form puts it" in str(
        misalignment(expected + 20 * millimetre, expected)
    )
    assert "turned" in str(misalignment(np.roll(expected, 1, axis=0), expected))
    centre = expected.mean(axis=0)
    assert "times its printed size" in str(
        misalignment(centre + (expected - centre) * 0.5, expected)
    )


# --- The Capture page ---------------------------------------------------------------


def test_read_it_anyway_on_the_capture_page(
    qtbot: QtBot, connection: sqlite3.Connection, shrunk_landscape: Path
) -> None:
    add_capture(connection, shrunk_landscape)
    page = CapturePage(connection)
    qtbot.addWidget(page)
    messages: list[str] = []
    page.status_message.connect(messages.append)
    assert not page.read_anyway_button.isEnabled()

    page.read_waiting()
    page.sheet_list.setCurrentRow(0)

    (capture,) = list_captures(connection)
    assert capture.status == CAPTURE_STATUSES.UNREADABLE
    assert "Read it anyway" in capture.problem
    assert page.read_anyway_button.isEnabled()

    page.read_anyway()

    (capture,) = list_captures(connection)
    assert capture.status == CAPTURE_STATUSES.READ
    assert not page.read_anyway_button.isEnabled()
    assert messages[-1] == (
        'Read "shrunk.jpg" by finding the page from its QR code. Check every '
        "answer against the sheet before saving."
    )
