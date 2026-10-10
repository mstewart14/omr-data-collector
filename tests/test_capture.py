"""Capturing filled-in sheets: adding images, reading them, checking the data."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QMessageBox

from omr_data_collector.constants import CAPTURE_STATUSES
from omr_data_collector.engine.reading import read_capture
from omr_data_collector.layout.omr_template import page_template
from omr_data_collector.storage.capture_store import (
    DuplicateCaptureError,
    add_capture,
    captures_dir,
    delete_capture,
    image_path,
    list_captures,
    load_capture,
    page_image_path,
)
from omr_data_collector.ui.CapturePage import CapturePage
from tests.sheets import LETTER, Sheet

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

    from omr_data_collector.layout.form_layout import FormLayout
    from omr_data_collector.models.Form import Form
    from omr_data_collector.models.Organization import Organization

pytestmark = pytest.mark.usefixtures("qapp")

# The intake form's page: two questions, then a six-row table of three columns.
ANSWERS_ON_PAGE = 2 + 6 * 3


@pytest.fixture
def photo(
    organization: Organization, printed_form: tuple[Form, FormLayout], tmp_path: Path
) -> Path:
    """A photo of the intake form with services Food and Other, and a table row."""
    form, layout = printed_form
    sheet = Sheet(form, organization, layout)
    sheet.fill_question(1, 0, 3)
    sheet.fill_cell(2, row=0, column=2, choice=1)
    return sheet.photograph(tmp_path / "upload" / "photo.jpg")


@pytest.fixture
def blank_image(tmp_path: Path) -> Path:
    import cv2  # noqa: PLC0415 (only this fixture draws with it)

    path = tmp_path / "upload" / "blank.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.full((400, 300), 255, dtype=np.uint8))
    return path


# --- Storage (wiki 60001-60002) ----------------------------------------------------


def test_an_added_image_is_copied_beside_the_database(
    connection: sqlite3.Connection, photo: Path
) -> None:
    capture = add_capture(connection, photo)

    assert capture.status == CAPTURE_STATUSES.WAITING
    assert capture.original_name == "photo.jpg"
    copy = image_path(connection, capture)
    assert copy.parent == captures_dir(connection)
    assert copy.read_bytes() == photo.read_bytes()
    assert list_captures(connection) == [capture]


def test_the_same_image_cant_be_added_twice(
    connection: sqlite3.Connection, photo: Path, tmp_path: Path
) -> None:
    first = add_capture(connection, photo)
    renamed = tmp_path / "same photo.jpg"
    renamed.write_bytes(photo.read_bytes())

    with pytest.raises(DuplicateCaptureError) as raised:
        add_capture(connection, renamed)

    assert raised.value.existing == first


def test_removing_a_capture_removes_its_images(
    connection: sqlite3.Connection, photo: Path
) -> None:
    capture = read_capture(connection, add_capture(connection, photo), LETTER)
    assert page_image_path(connection, capture).exists()

    delete_capture(connection, capture)

    assert list_captures(connection) == []
    assert not image_path(connection, capture).exists()
    assert not page_image_path(connection, capture).exists()


# --- Reading (wiki 60003) ------------------------------------------------------------


def test_reading_finds_the_page_and_every_answer_on_it(
    connection: sqlite3.Connection,
    photo: Path,
    printed_form: tuple[Form, FormLayout],
) -> None:
    form, _ = printed_form

    capture = read_capture(connection, add_capture(connection, photo), LETTER)

    assert capture.status == CAPTURE_STATUSES.READ
    assert (capture.form_id, capture.form_version, capture.page) == (
        form.form_id,
        form.version,
        1,
    )
    assert len(capture.answers) == ANSWERS_ON_PAGE
    services = capture.answer((1, None, None))
    assert services is not None
    assert services.scanned == services.values == ("food", "other")
    cell = capture.answer((2, 0, 2))
    assert cell is not None
    assert cell.values == ("clothing",)
    time = capture.answer((2, 0, 0))
    assert time is not None
    assert time.values == ()  # handwritten: typed in when checking
    assert page_image_path(connection, capture).exists()
    assert load_capture(connection, capture.capture_id) == capture


def test_an_unreadable_image_is_kept_with_the_reason(
    connection: sqlite3.Connection, blank_image: Path
) -> None:
    capture = read_capture(connection, add_capture(connection, blank_image), LETTER)

    assert capture.status == CAPTURE_STATUSES.UNREADABLE
    assert "QR code" in capture.problem
    assert capture.answers == ()


def test_every_answer_has_a_region_on_the_page(
    printed_form: tuple[Form, FormLayout],
) -> None:
    _, layout = printed_form

    template = page_template(layout, layout.pages[0])

    width, height = template.template["templateDimensions"]
    assert len(template.regions) == ANSWERS_ON_PAGE
    for region in template.regions:
        x, y, region_width, region_height = region.rect
        assert 0 <= x < x + region_width <= width
        assert 0 <= y < y + region_height <= height


# --- Checking (wiki 60004) -----------------------------------------------------------


def make_page(qtbot: QtBot, connection: sqlite3.Connection) -> CapturePage:
    page = CapturePage(connection)
    qtbot.addWidget(page)
    page.resize(1200, 800)
    return page


def add_through_page(
    page: CapturePage, mocker: MockerFixture, *paths: Path
) -> list[str]:
    mocker.patch(
        "omr_data_collector.ui.CapturePage.choose_images", return_value=list(paths)
    )
    messages: list[str] = []
    page.status_message.connect(messages.append)
    page.add_images()
    return messages


def cell_text(page: CapturePage, row: int, column: int) -> str:
    item = page.answers_table.item(row, column)
    return item.text() if item is not None else ""


def row_of(page: CapturePage, name: str) -> int:
    return next(
        row
        for row in range(page.answers_table.rowCount())
        if cell_text(page, row, 0) == name
    )


def test_added_images_wait_to_be_read(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    photo: Path,
    blank_image: Path,
) -> None:
    page = make_page(qtbot, connection)

    messages = add_through_page(page, mocker, photo, blank_image, photo)

    assert [page.sheet_list.item(row).text() for row in range(2)] == [
        "photo.jpg: waiting to be read",
        "blank.png: waiting to be read",
    ]
    assert messages == [
        "Added 2 images. Read waiting sheets reads them. "
        "Already added, so skipped: photo.jpg."
    ]
    assert page.read_button.isEnabled()
    assert not page.save_button.isEnabled()


def test_reading_shows_the_sheets_answers_to_check(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    photo: Path,
    blank_image: Path,
) -> None:
    page = make_page(qtbot, connection)
    add_through_page(page, mocker, photo, blank_image)
    messages: list[str] = []
    page.status_message.connect(messages.append)

    page.read_waiting()

    assert messages == ["Read 1 sheet. 1 couldn't be read; choose one to see why."]
    assert page.sheet_list.item(0).text() == "photo.jpg: read, to check"
    assert page.sheet_list.item(1).text() == "blank.png: couldn't be read"
    assert page.answers_table.rowCount() == ANSWERS_ON_PAGE
    services = row_of(page, "services")
    assert cell_text(page, services, 1) == "Food, Other"
    time = row_of(page, "Log, row 1, time")
    assert cell_text(page, time, 2) == "Handwritten: type it in"
    assert page.sheet_canvas.has_image()

    page.sheet_list.setCurrentRow(1)

    assert "QR code" in page.sheet_note.text()
    assert page.answers_table.rowCount() == 0


def test_choosing_an_answer_outlines_it_and_shows_a_close_up(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture, photo: Path
) -> None:
    page = make_page(qtbot, connection)
    add_through_page(page, mocker, photo)
    page.read_waiting()

    page.answers_table.selectRow(row_of(page, "services"))

    assert page.sheet_canvas.current() == row_of(page, "services")
    assert not page.close_up.pixmap().isNull()
    assert page.value_label.text() == "Va&lue of services"
    assert page.value_label.buddy() is page.answer_editor.choices_list


def test_a_handwritten_answer_is_checked_before_saving(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture, photo: Path
) -> None:
    page = make_page(qtbot, connection)
    add_through_page(page, mocker, photo)
    page.read_waiting()
    messages: list[str] = []
    page.status_message.connect(messages.append)
    page.answers_table.selectRow(row_of(page, "Log, row 1, time"))
    page.answer_editor.text_edit.setText("25:99")
    page.answer_editor.text_edit.textEdited.emit("25:99")

    assert page.has_unsaved_changes()
    assert not page.save_data()

    assert messages == ["1 answer to fix before saving."]
    assert "real date or time" in page.value_error.text()

    page.answer_editor.text_edit.setText("09:30")
    page.answer_editor.text_edit.textEdited.emit("09:30")

    assert page.save_data()
    (capture,) = list_captures(connection)
    assert capture.status == CAPTURE_STATUSES.SAVED
    time = capture.answer((2, 0, 0))
    assert time is not None
    assert time.values == ("09:30",)
    assert page.sheet_list.item(0).text() == "photo.jpg: saved"
    assert not page.has_unsaved_changes()


def test_two_marks_where_one_is_allowed_must_be_settled(  # noqa: PLR0913 (fixtures)
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    form, layout = printed_form
    sheet = Sheet(form, organization, layout)
    sheet.fill_cell(2, row=1, column=2, choice=0)
    sheet.fill_cell(2, row=1, column=2, choice=1)
    page = make_page(qtbot, connection)
    add_through_page(page, mocker, sheet.photograph(tmp_path / "double.jpg"))
    page.read_waiting()
    row = row_of(page, "Log, row 2, service")
    page.answers_table.selectRow(row)

    assert page.answer_editor.choice_combo.currentText() == "More than one marked"
    assert not page.save_data()

    page.answer_editor.choice_combo.setCurrentIndex(
        page.answer_editor.choice_combo.findText("C")
    )

    assert page.save_data()
    capture = list_captures(connection)[0]
    cell = capture.answer((2, 1, 2))
    assert cell is not None
    assert cell.values == ("clothing",)


def test_a_rejected_sheet_is_kept_out_of_the_data(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture, photo: Path
) -> None:
    page = make_page(qtbot, connection)
    add_through_page(page, mocker, photo)
    page.read_waiting()

    page.reject_sheet()

    (capture,) = list_captures(connection)
    assert capture.status == CAPTURE_STATUSES.REJECTED
    assert page.sheet_list.item(0).text() == "photo.jpg: rejected"
    assert not page.reject_button.isEnabled()


def test_removing_a_sheet_asks_first(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture, photo: Path
) -> None:
    page = make_page(qtbot, connection)
    add_through_page(page, mocker, photo)
    confirm = mocker.patch(
        "omr_data_collector.ui.CapturePage.confirm_destructive", return_value=False
    )

    page.remove_sheet()

    assert len(list_captures(connection)) == 1
    confirm.return_value = True

    page.remove_sheet()

    assert list_captures(connection) == []
    assert page.empty_note.isVisibleTo(page)


def test_leaving_a_sheet_with_changes_asks_about_them(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    photo: Path,
    blank_image: Path,
) -> None:
    page = make_page(qtbot, connection)
    add_through_page(page, mocker, photo, blank_image)
    page.read_waiting()
    page.sheet_list.setCurrentRow(0)
    page.answers_table.selectRow(row_of(page, "services"))
    page.answer_editor.choices_list.item(1).setCheckState(
        page.answer_editor.choices_list.item(1).checkState().Checked
    )
    ask = mocker.patch(
        "omr_data_collector.ui.CapturePage.ask_save_discard_cancel",
        return_value=QMessageBox.StandardButton.Cancel,
    )

    page.sheet_list.setCurrentRow(1)

    ask.assert_called_once()
    assert page.sheet_list.currentRow() == 0
    assert page.has_unsaved_changes()

    page.revert()

    assert not page.has_unsaved_changes()


# --- Working on the sheet itself ---------------------------------------------------


@pytest.fixture
def checking(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture, photo: Path
) -> CapturePage:
    """The capture page, shown, with the photo read and ready to check."""
    page = make_page(qtbot, connection)
    page.show()
    add_through_page(page, mocker, photo)
    page.read_waiting()
    qtbot.waitExposed(page)
    # Keyboard focus only goes to widgets in the active window.
    page.activateWindow()
    qtbot.waitActive(page)
    return page


def click_answer(qtbot: QtBot, page: CapturePage, name: str) -> int:
    row = row_of(page, name)
    canvas = page.sheet_canvas
    page.sheet_scroll.ensureWidgetVisible(canvas)
    qtbot.mouseClick(
        canvas, Qt.MouseButton.LeftButton, pos=canvas.answer_rect_in_view(row).center()
    )
    return row


def test_clicking_a_handwritten_answer_lets_you_type_at_once(
    qtbot: QtBot, checking: CapturePage
) -> None:
    canvas = checking.sheet_canvas
    row = click_answer(qtbot, checking, "Log, row 1, time")

    assert canvas.current() == row
    assert canvas.editor.isVisible()
    assert canvas.editor.hasFocus()
    qtbot.keyClicks(canvas.editor, "09:30")

    assert canvas.answer(row).values == ("09:30",)  # drawn over the sheet
    assert cell_text(checking, row, 1) == "09:30"
    assert checking.answers_table.currentRow() == row
    assert checking.save_data()


def test_tab_and_arrows_go_from_answer_to_answer(
    qtbot: QtBot, checking: CapturePage
) -> None:
    canvas = checking.sheet_canvas
    start = click_answer(qtbot, checking, "Log, row 1, time")

    qtbot.keyClick(canvas.editor, Qt.Key.Key_Tab)

    assert canvas.current() == row_of(checking, "Log, row 1, first")
    assert canvas.hasFocus()  # a bubble answer: the keys choose

    qtbot.keyClick(canvas, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    assert canvas.current() == start

    qtbot.keyClick(canvas.editor, Qt.Key.Key_Down)
    assert canvas.current() == row_of(checking, "Log, row 2, time")

    qtbot.keyClick(canvas.editor, Qt.Key.Key_Right)  # at the end of empty text
    assert canvas.current() == row_of(checking, "Log, row 2, first")


def test_clicking_a_bubble_marks_it(qtbot: QtBot, checking: CapturePage) -> None:
    canvas = checking.sheet_canvas
    row = row_of(checking, "services")
    bubble = canvas.answer(row).bubbles[1]  # Clothing
    x, y, width, height = bubble
    scale = canvas.width() / canvas._pixmap.width()  # noqa: SLF001 (drawn size)
    point = QPoint(round((x + width / 2) * scale), round((y + height / 2) * scale))

    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)

    assert canvas.answer(row).values == ("food", "clothing", "other")
    assert cell_text(checking, row, 1) == "Food, Clothing, Other"

    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)

    assert canvas.answer(row).values == ("food", "other")


def test_number_keys_choose_and_delete_clears(
    qtbot: QtBot, checking: CapturePage
) -> None:
    canvas = checking.sheet_canvas
    row = row_of(checking, "Log, row 1, service")  # Clothing marked on the photo
    canvas.set_current(row, focus=True)

    qtbot.keyClick(canvas, Qt.Key.Key_3)

    assert canvas.answer(row).values == ("referral",)

    qtbot.keyClick(canvas, Qt.Key.Key_3)  # pressed again, like re-marking: clears

    assert canvas.answer(row).values == ()

    qtbot.keyClick(canvas, Qt.Key.Key_1)

    assert canvas.answer(row).values == ("food",)

    qtbot.keyClick(canvas, Qt.Key.Key_Delete)

    assert canvas.answer(row).values == ()


def test_space_marks_or_clears_a_yes_no_bubble(
    qtbot: QtBot, checking: CapturePage
) -> None:
    canvas = checking.sheet_canvas
    row = row_of(checking, "visit")
    canvas.set_current(row, focus=True)
    assert canvas.answer(row).values == ("no",)

    qtbot.keyClick(canvas, Qt.Key.Key_Space)

    assert canvas.answer(row).values == ("yes",)
    assert cell_text(checking, row, 1) == "Yes"

    qtbot.keyClick(canvas, Qt.Key.Key_Space)

    assert canvas.answer(row).values == ("no",)


def test_the_side_editor_and_the_sheet_show_the_same_value(
    checking: CapturePage,
) -> None:
    row = row_of(checking, "Log, row 2, time")
    checking.answers_table.selectRow(row)
    checking.answer_editor.text_edit.setText("10:15")
    checking.answer_editor.text_edit.textEdited.emit("10:15")

    assert checking.sheet_canvas.answer(row).values == ("10:15",)
    assert checking.sheet_canvas.current() == row
