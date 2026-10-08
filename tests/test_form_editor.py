from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PySide6.QtCore import QByteArray, QMimeData, QPointF, Qt
from PySide6.QtGui import QColor, QDropEvent, QImage, QPainter
from PySide6.QtWidgets import QDialogButtonBox, QMessageBox
from pyzbar.pyzbar import decode

from omr_data_collector.constants import ANSWER_TYPES, BLOCK_KINDS, PAPER_SIZES
from omr_data_collector.identity.qr_code import parse_payload
from omr_data_collector.layout.form_layout import QR_SIZE_MM, layout_form
from omr_data_collector.layout.page_setup import PAGE_MARGIN_MM
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.Organization import Organization
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.rendering.page_painter import paint_page
from omr_data_collector.storage.form_store import save_form
from omr_data_collector.storage.organization_store import save_organization
from omr_data_collector.storage.question_store import save_question
from omr_data_collector.storage.table_block_store import save_table_block
from omr_data_collector.storage.text_block_store import save_text_block
from omr_data_collector.ui.BlockPalette import BlockPalette
from omr_data_collector.ui.FormsPage import FormsPage
from omr_data_collector.ui.OpenFormDialog import OpenFormDialog
from omr_data_collector.ui.PageCanvas import (
    FORM_BLOCK_MIME,
    LIBRARY_BLOCK_MIME,
    PageCanvas,
    library_block_mime,
)

if TYPE_CHECKING:
    import sqlite3

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

ORGANIZATION = Organization(name="Food Bank", phone="613-555-0123")
TITLE = TextBlock(name="Title", content="# Client intake")
FOOTER = TextBlock(name="Footer", content="Thank you.")
VISIT = Question(
    name="first_visit",
    prompt="Is this your first visit?",
    answer=AnswerSpec(ANSWER_TYPES.YES_NO, choices=(Choice("Yes"), Choice("No"))),
).normalized()
LOG = TableBlock(
    name="Visit log",
    rows=40,
    columns=(
        Column("time", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=5)),
    ),
)


def intake() -> Form:
    return Form(
        name="Intake",
        blocks=(
            FormBlock(TITLE, TITLE.text_block_id),
            FormBlock(VISIT, VISIT.question_id),
            FormBlock(LOG, LOG.table_block_id),
        ),
    ).normalized()


def make_page(qtbot: QtBot, connection: sqlite3.Connection) -> FormsPage:
    page = FormsPage(connection)
    qtbot.addWidget(page)
    return page


def names(page: FormsPage) -> list[str]:
    return [block.content.name for block in page.read_item("f", "x" * 32).blocks]


def drop(canvas: PageCanvas, mime: QMimeData, position: QPointF) -> None:
    event = QDropEvent(
        position,
        Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.dropEvent(event)


@pytest.fixture
def stocked(connection: sqlite3.Connection) -> sqlite3.Connection:
    """A database with an organization, some library blocks and a saved form."""
    save_organization(connection, ORGANIZATION)
    save_text_block(connection, TITLE)
    save_text_block(connection, FOOTER)
    save_question(connection, VISIT)
    save_table_block(connection, LOG)
    save_form(connection, intake())
    return connection


# --- Printed pages ----------------------------------------------------------------


@pytest.mark.usefixtures("qapp")
def test_each_page_carries_a_qr_code_naming_the_form_version_and_page() -> None:
    form = Form(name="Intake", version=3, blocks=intake().blocks)
    layout = layout_form(form, PAPER_SIZES.LETTER)
    assert len(layout.pages) == 2
    pixels_per_mm = 8

    for page in layout.pages:
        image = QImage(
            int((layout.width_mm + 2 * PAGE_MARGIN_MM) * pixels_per_mm),
            int((layout.height_mm + 2 * PAGE_MARGIN_MM) * pixels_per_mm),
            QImage.Format.Format_Grayscale8,
        )
        image.fill(QColor("white"))
        painter = QPainter(image)
        painter.scale(pixels_per_mm, pixels_per_mm)
        painter.translate(PAGE_MARGIN_MM, PAGE_MARGIN_MM)
        paint_page(painter, form, ORGANIZATION, layout, page)
        painter.end()

        pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
            image.height(), image.bytesPerLine()
        )[:, : image.width()]
        (symbol,) = decode(pixels)
        payload = parse_payload(symbol.data.decode())
        assert payload == {
            "type": "form",
            "version": 1,
            "organizationId": ORGANIZATION.organization_id,
            "formId": form.form_id,
            "formVersion": 3,
            "page": page.number,
        }
        # In the top-right corner of the printable area.
        left = min(point.x for point in symbol.polygon) / pixels_per_mm - PAGE_MARGIN_MM
        assert left > layout.width_mm - QR_SIZE_MM


@pytest.mark.usefixtures("qapp")
def test_pages_paint_without_an_organization() -> None:
    form = intake()
    layout = layout_form(form, PAPER_SIZES.A4)
    image = QImage(800, 1100, QImage.Format.Format_Grayscale8)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.scale(3, 3)
    paint_page(painter, form, None, layout, layout.pages[0])
    painter.end()

    pixels = np.frombuffer(image.constBits(), dtype=np.uint8)
    assert (pixels < 128).any()  # the blocks and the QR placeholder were drawn


# --- The canvas -------------------------------------------------------------------


def shown_canvas(qtbot: QtBot, form: Form) -> PageCanvas:
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(700, 400)
    canvas.set_form(form, ORGANIZATION, PAPER_SIZES.LETTER)
    return canvas


def test_canvas_finds_the_block_under_the_pointer(qtbot: QtBot) -> None:
    canvas = shown_canvas(qtbot, intake())

    for area in canvas._areas:  # noqa: SLF001 (checking the hit areas it draws)
        assert canvas.block_at(area.rect.center()) == area.index
    assert canvas.block_at(QPointF(2, 2)) == -1


def test_canvas_describes_its_pages_for_screen_readers(qtbot: QtBot) -> None:
    canvas = shown_canvas(qtbot, intake())

    description = canvas.accessibleDescription()

    assert description.startswith(
        "2 pages. Page 1: Title, first_visit, Visit log (rows 1 to "
    )
    assert "Page 2: Visit log (rows " in description
    assert description.endswith(" to 40).")


def test_dropping_a_form_block_asks_to_move_it(qtbot: QtBot) -> None:
    canvas = shown_canvas(qtbot, intake())
    title_area = next(area for area in canvas._areas if area.index == 0)  # noqa: SLF001
    mime = QMimeData()
    mime.setData(FORM_BLOCK_MIME, QByteArray(b"2"))

    with qtbot.waitSignal(canvas.block_moved) as moved:
        drop(
            canvas,
            mime,
            QPointF(title_area.rect.center().x(), title_area.rect.top() + 1),
        )

    assert moved.args == [2, 0]


def test_dropping_a_library_block_asks_to_add_it_there(qtbot: QtBot) -> None:
    canvas = shown_canvas(qtbot, intake())
    question_area = next(area for area in canvas._areas if area.index == 1)  # noqa: SLF001

    with qtbot.waitSignal(canvas.library_block_dropped) as dropped:
        drop(
            canvas,
            library_block_mime(BLOCK_KINDS.TEXT, FOOTER.text_block_id),
            QPointF(question_area.rect.center().x(), question_area.rect.bottom() - 1),
        )

    assert dropped.args == [BLOCK_KINDS.TEXT, FOOTER.text_block_id, 2]


def test_library_drag_data_names_the_kind_and_block() -> None:
    mime = library_block_mime(BLOCK_KINDS.QUESTION, VISIT.question_id)

    data = json.loads(bytes(mime.data(LIBRARY_BLOCK_MIME).data()).decode())

    assert data == {"kind": BLOCK_KINDS.QUESTION, "id": VISIT.question_id}


def test_canvas_only_takes_keyboard_focus_through_the_outline(qtbot: QtBot) -> None:
    canvas = shown_canvas(qtbot, intake())

    assert canvas.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert canvas.accessibleName() == "Form pages"


# --- The palette --------------------------------------------------------------------


def test_palette_lists_library_blocks_and_adds_the_selected_one(qtbot: QtBot) -> None:
    palette = BlockPalette()
    qtbot.addWidget(palette)
    palette.set_items(BLOCK_KINDS.TEXT, [FOOTER, TITLE])
    texts = palette.lists[BLOCK_KINDS.TEXT]
    assert not palette.add_buttons[BLOCK_KINDS.TEXT].isEnabled()

    texts.setCurrentRow(1)
    with qtbot.waitSignal(palette.add_requested) as added:
        palette.add_buttons[BLOCK_KINDS.TEXT].click()

    assert added.args == [BLOCK_KINDS.TEXT, TITLE.text_block_id]
    mime = texts.mimeData([texts.item(0)])
    assert json.loads(bytes(mime.data(LIBRARY_BLOCK_MIME).data()).decode())["id"] == (
        FOOTER.text_block_id
    )


# --- The editor page ------------------------------------------------------------------


def test_editor_shows_the_form_on_its_pages(
    qtbot: QtBot, stocked: sqlite3.Connection
) -> None:
    page = make_page(qtbot, stocked)

    layout = page.canvas.form_layout
    assert layout is not None
    assert [placed.index for placed in layout.pages[0].blocks][:2] == [0, 1]
    assert page.item_list.isHidden() or not page.item_list.isVisibleTo(page)


def test_clicking_a_block_on_the_page_selects_it_in_the_outline(
    qtbot: QtBot, stocked: sqlite3.Connection
) -> None:
    page = make_page(qtbot, stocked)
    page.resize(1300, 800)
    page.show()
    qtbot.waitExposed(page)
    area = next(area for area in page.canvas._areas if area.index == 1)  # noqa: SLF001

    qtbot.mouseClick(
        page.canvas, Qt.MouseButton.LeftButton, pos=area.rect.center().toPoint()
    )

    assert page.block_list.currentRow() == 1
    assert page.canvas.selected_index == 1


def test_dropping_on_the_page_adds_a_copy_there(
    qtbot: QtBot, stocked: sqlite3.Connection
) -> None:
    page = make_page(qtbot, stocked)

    page.canvas.library_block_dropped.emit(BLOCK_KINDS.TEXT, FOOTER.text_block_id, 1)

    assert names(page) == ["Title", "Footer", "first_visit", "Visit log"]
    (footer,) = [
        b for b in page.read_item("f", "x" * 32).blocks if b.content.name == "Footer"
    ]
    assert footer.source_id == FOOTER.text_block_id
    assert page.has_unsaved_changes()


@pytest.mark.parametrize(
    ("from_index", "insert_index", "expected"),
    [
        (2, 0, ["Visit log", "Title", "first_visit"]),
        (0, 3, ["first_visit", "Visit log", "Title"]),
        (0, 2, ["first_visit", "Title", "Visit log"]),
        (1, 1, ["Title", "first_visit", "Visit log"]),
        (1, 2, ["Title", "first_visit", "Visit log"]),
    ],
)
def test_dragging_a_block_moves_it(
    qtbot: QtBot,
    stocked: sqlite3.Connection,
    from_index: int,
    insert_index: int,
    expected: list[str],
) -> None:
    page = make_page(qtbot, stocked)

    page.canvas.block_moved.emit(from_index, insert_index)

    assert names(page) == expected


def test_palette_add_puts_the_block_under_the_selection(
    qtbot: QtBot, stocked: sqlite3.Connection
) -> None:
    page = make_page(qtbot, stocked)
    page.block_list.setCurrentRow(0)

    page.block_palette.add_requested.emit(BLOCK_KINDS.QUESTION, VISIT.question_id)

    assert names(page)[:2] == ["Title", "first_visit"]
    assert page.block_list.currentRow() == 1


def test_palette_refreshes_when_the_editor_is_shown(
    qtbot: QtBot, stocked: sqlite3.Connection
) -> None:
    page = make_page(qtbot, stocked)
    save_text_block(stocked, TextBlock(name="Added later", content="x"))

    page.show()

    texts = page.block_palette.lists[BLOCK_KINDS.TEXT]
    assert "Added later" in [texts.item(row).text() for row in range(texts.count())]


def test_double_clicking_a_block_edits_the_forms_copy(
    qtbot: QtBot, stocked: sqlite3.Connection, mocker: MockerFixture
) -> None:
    page = make_page(qtbot, stocked)
    write = mocker.patch(
        "omr_data_collector.ui.FormsPage.write_block", return_value=None
    )

    page.canvas.block_activated.emit(1)

    assert write.call_args.args[1:] == (BLOCK_KINDS.QUESTION, VISIT)


def test_open_form_opens_the_chosen_one(
    qtbot: QtBot, stocked: sqlite3.Connection, mocker: MockerFixture
) -> None:
    other = save_form(stocked, Form(name="Exit survey", blocks=(FormBlock(FOOTER),)))
    page = make_page(qtbot, stocked)
    choose = mocker.patch(
        "omr_data_collector.ui.FormsPage.choose_form", return_value=other.form_id
    )

    page.open_from_list()

    forms, printed = choose.call_args.args[1:]
    assert sorted(form.name for form in forms) == ["Exit survey", "Intake"]
    assert printed == set()
    assert page.name_edit.text() == "Exit survey"


def test_open_form_asks_about_unsaved_changes_first(
    qtbot: QtBot, stocked: sqlite3.Connection, mocker: MockerFixture
) -> None:
    other = save_form(stocked, Form(name="Exit survey", blocks=(FormBlock(FOOTER),)))
    page = make_page(qtbot, stocked)
    page.name_edit.setText("Intake (edited)")
    mocker.patch(
        "omr_data_collector.ui.FormsPage.choose_form", return_value=other.form_id
    )
    mocker.patch(
        "omr_data_collector.ui.LibraryPage.ask_save_discard_cancel",
        return_value=QMessageBox.StandardButton.Cancel,
    )

    page.open_from_list()

    assert page.name_edit.text() == "Intake (edited)"
    page.revert()


# --- Open form dialog -------------------------------------------------------------


def test_open_dialog_lists_forms_with_their_version_and_print_state(
    qtbot: QtBot,
) -> None:
    intake_form = Form(name="Intake", version=2, blocks=intake().blocks)
    survey = Form(name="Exit survey", version=1, blocks=(FormBlock(FOOTER),))
    dialog = OpenFormDialog(None, [survey, intake_form], {intake_form.form_id})
    qtbot.addWidget(dialog)

    texts = [
        dialog.form_list.item(row).text() for row in range(dialog.form_list.count())
    ]

    assert texts == [
        "Exit survey (version 1, not printed yet)",
        "Intake (version 2, printed)",
    ]
    dialog.form_list.setCurrentRow(1)
    assert dialog.chosen_form_id() == intake_form.form_id
    assert dialog.empty_note.isHidden()


def test_open_dialog_with_no_forms_says_so(qtbot: QtBot) -> None:
    dialog = OpenFormDialog(None, [], set())
    qtbot.addWidget(dialog)

    assert not dialog.empty_note.isHidden()
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Open).isEnabled()
    assert dialog.chosen_form_id() is None
