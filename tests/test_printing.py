"""Saving forms as PDFs, print preview and printing (wiki 50007-50009)."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPrintSupport import QPrinter

from omr_data_collector.constants import (
    ANSWER_TYPES,
    PAGE_ORIENTATIONS,
    PAPER_SIZES,
)
from omr_data_collector.identity.qr_code import parse_payload, read_qr_codes
from omr_data_collector.layout.form_layout import layout_form
from omr_data_collector.layout.frozen_layout import FROZEN_LAYOUT_KEY, thawed_layout
from omr_data_collector.layout.omr_template import printed_layout
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.FormFont import FormFont
from omr_data_collector.models.Organization import Organization
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.rendering.print_form import save_pdf
from omr_data_collector.storage.form_store import (
    is_printed,
    list_forms,
    load_printed_layout,
    mark_printed,
    save_form,
)
from omr_data_collector.storage.organization_store import save_organization
from omr_data_collector.ui.FormsPage import FormsPage
from omr_data_collector.ui.MainWindow import MainWindow

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

PAGE_MODULE = "omr_data_collector.ui.FormsPage"
ORGANIZATION = Organization(name="Food Bank", phone="613-555-0123")
VISIT = Question(
    name="first_visit",
    prompt="Is this your first visit?",
    answer=AnswerSpec(ANSWER_TYPES.YES_NO, choices=(Choice("Yes"), Choice("No"))),
).normalized()
LOG = TableBlock(
    name="Visit log",
    rows=45,
    columns=(
        Column("time", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=5)),
    ),
)


def intake(**changes: object) -> Form:
    form = Form(
        name="Intake",
        blocks=(
            FormBlock(TextBlock("Title", "# Client intake")),
            FormBlock(VISIT),
            FormBlock(LOG),
        ),
    ).normalized()
    return replace(form, **changes)  # type: ignore[arg-type]


def pdf_pages(path: Path) -> list[QImage]:
    document = QPdfDocument()
    document.load(str(path))
    pages = []
    for number in range(document.pageCount()):
        size = document.pagePointSize(number)
        pages.append(
            document.render(
                number, QSize(int(size.width() * 3), int(size.height() * 3))
            )
        )
    return pages


def qr_payload(image: QImage) -> dict:
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    pixels = np.frombuffer(gray.constBits(), dtype=np.uint8).reshape(
        gray.height(), gray.bytesPerLine()
    )[:, : gray.width()]
    (text,) = read_qr_codes(pixels)
    return parse_payload(text)


def pdf_page_size(path: Path) -> tuple[float, float]:
    document = QPdfDocument()
    document.load(str(path))
    size = document.pagePointSize(0)
    return round(size.width()), round(size.height())


# --- The PDF itself ---------------------------------------------------------------


@pytest.mark.usefixtures("qapp")
def test_pdf_has_every_page_each_with_its_own_qr_code(tmp_path: Path) -> None:
    form = intake(version=4)
    path = tmp_path / "intake.pdf"

    pages = save_pdf(path, form, ORGANIZATION, PAPER_SIZES.LETTER)

    images = pdf_pages(path)
    assert pages == len(images) == 2
    for number, image in enumerate(images, start=1):
        payload = qr_payload(image)
        assert (payload["formId"], payload["formVersion"], payload["page"]) == (
            form.form_id,
            4,
            number,
        )


@pytest.mark.usefixtures("qapp")
@pytest.mark.parametrize(
    ("paper_size", "orientation", "points"),
    [
        (PAPER_SIZES.LETTER, PAGE_ORIENTATIONS.PORTRAIT, (612, 792)),
        (PAPER_SIZES.LETTER, PAGE_ORIENTATIONS.LANDSCAPE, (792, 612)),
        (PAPER_SIZES.LEGAL, PAGE_ORIENTATIONS.PORTRAIT, (612, 1008)),
        (PAPER_SIZES.A4, PAGE_ORIENTATIONS.PORTRAIT, (595, 842)),
    ],
)
def test_pdf_pages_are_the_organizations_paper_in_the_forms_orientation(
    tmp_path: Path, paper_size: str, orientation: str, points: tuple[int, int]
) -> None:
    path = tmp_path / "form.pdf"

    save_pdf(path, intake(version=1, orientation=orientation), ORGANIZATION, paper_size)

    assert pdf_page_size(path) == points


# --- The editor's commands ------------------------------------------------------------


@pytest.fixture
def page(qtbot: QtBot, connection: sqlite3.Connection) -> FormsPage:
    save_organization(connection, ORGANIZATION)
    save_form(connection, intake())
    editor = FormsPage(connection)
    qtbot.addWidget(editor)
    return editor


def statuses_of(page: FormsPage) -> list[str]:
    statuses: list[str] = []
    page.status_message.connect(statuses.append)
    return statuses


def test_export_pdf_saves_the_file_and_keeps_the_version_as_printed(
    page: FormsPage,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    path = tmp_path / "Intake v1.pdf"
    choose = mocker.patch(f"{PAGE_MODULE}.choose_pdf_path", return_value=path)
    statuses = statuses_of(page)

    page.export_pdf()

    assert choose.call_args.args[1] == "Intake v1.pdf"
    assert len(pdf_pages(path)) == 2
    (form,) = list_forms(connection)
    assert is_printed(connection, form.form_id, 1)
    assert statuses[-1] == (
        f"Saved 2 pages to {path}. Version 1 is now kept as printed; changes from "
        "here make version 2."
    )
    assert page.version_note.text().startswith("Version 1 has been printed")


def test_changes_after_printing_save_as_the_next_version(
    page: FormsPage,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    mocker.patch(f"{PAGE_MODULE}.choose_pdf_path", return_value=tmp_path / "a.pdf")
    page.export_pdf()

    page.set_selection([0])
    page.remove_selected_blocks()
    page.save()

    (form,) = list_forms(connection)
    assert form.version == 2


def test_unsaved_changes_are_saved_first_when_agreed(
    page: FormsPage,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    page.set_selection([0])
    page.remove_selected_blocks()
    ask = mocker.patch(f"{PAGE_MODULE}.ask_save_first", return_value=True)
    mocker.patch(f"{PAGE_MODULE}.choose_pdf_path", return_value=tmp_path / "a.pdf")

    page.export_pdf()

    assert "save it as a PDF" in ask.call_args.args[1]
    (form,) = list_forms(connection)
    assert [block.content.name for block in form.blocks] == ["first_visit", "Visit log"]
    assert is_printed(connection, form.form_id, form.version)


def test_declining_to_save_prints_nothing(
    page: FormsPage, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    page.set_selection([0])
    page.remove_selected_blocks()
    mocker.patch(f"{PAGE_MODULE}.ask_save_first", return_value=False)
    choose = mocker.patch(f"{PAGE_MODULE}.choose_pdf_path")

    page.export_pdf()

    choose.assert_not_called()
    (form,) = list_forms(connection)
    assert not is_printed(connection, form.form_id, 1)
    page.revert()


def test_printing_needs_the_organizations_details(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_form(connection, intake())
    editor = FormsPage(connection)
    qtbot.addWidget(editor)
    tell = mocker.patch(f"{PAGE_MODULE}.tell")
    choose = mocker.patch(f"{PAGE_MODULE}.choose_pdf_path")

    with qtbot.waitSignal(editor.organization_needed):
        editor.export_pdf()

    assert "Preferences > Organization details" in tell.call_args.args[2]
    choose.assert_not_called()


@pytest.mark.parametrize("go_ahead", [True, False])
def test_layout_problems_are_shown_before_printing(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    tmp_path: Path,
    go_ahead: bool,  # noqa: FBT001
) -> None:
    save_organization(connection, ORGANIZATION)
    wide = TableBlock(
        name="Wide",
        columns=tuple(
            Column(f"c{n}", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=6))
            for n in range(8)
        ),
    )
    save_form(connection, Form(name="Wide form", blocks=(FormBlock(wide),)))
    editor = FormsPage(connection)
    qtbot.addWidget(editor)
    assert editor.problems_note.text().startswith("Check before printing: The table")
    confirm = mocker.patch(
        f"{PAGE_MODULE}.confirm_despite_problems", return_value=go_ahead
    )
    path = tmp_path / "wide.pdf"
    mocker.patch(f"{PAGE_MODULE}.choose_pdf_path", return_value=path)

    editor.export_pdf()

    assert "is 264 mm wide" in confirm.call_args.args[2][0]
    assert path.exists() == go_ahead


def test_print_sends_every_page_to_the_printer(
    page: FormsPage,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    output = tmp_path / "printed.pdf"

    def choose_printer(_parent, printer: QPrinter) -> bool:
        # Stands in for picking a printer: "print" to a PDF file instead.
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(output))
        return True

    mocker.patch(f"{PAGE_MODULE}.run_print_dialog", side_effect=choose_printer)

    page.print_form()

    assert len(pdf_pages(output)) == 2
    (form,) = list_forms(connection)
    assert is_printed(connection, form.form_id, 1)


def test_cancelling_the_print_dialog_keeps_the_version_open(
    page: FormsPage, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    mocker.patch(f"{PAGE_MODULE}.run_print_dialog", return_value=False)

    page.print_form()

    (form,) = list_forms(connection)
    assert not is_printed(connection, form.form_id, 1)


@pytest.mark.parametrize("printed", [True, False])
def test_print_preview_draws_the_pages_and_counts_only_if_printed(
    page: FormsPage,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    tmp_path: Path,
    printed: bool,  # noqa: FBT001
) -> None:
    output = tmp_path / "preview.pdf"

    def preview(_parent, printer: QPrinter, render) -> bool:
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(output))
        render(printer)
        return printed

    mocker.patch(f"{PAGE_MODULE}.run_print_preview", side_effect=preview)

    page.print_preview()

    assert len(pdf_pages(output)) == 2
    (form,) = list_forms(connection)
    assert is_printed(connection, form.form_id, 1) == printed


def test_file_menu_print_commands_open_the_form_editor(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_organization(connection, ORGANIZATION)
    save_form(connection, intake())
    window = MainWindow(connection)
    qtbot.addWidget(window)
    window.open_section(1)
    print_dialog = mocker.patch(f"{PAGE_MODULE}.run_print_dialog", return_value=False)

    next(
        action for action in window.file_menu.actions() if action.text() == "&Print…"
    ).trigger()

    assert window.stack.currentWidget() is window.forms_page
    print_dialog.assert_called_once()


def test_missing_organization_opens_its_details(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_form(connection, intake())
    window = MainWindow(connection)
    qtbot.addWidget(window)
    mocker.patch(f"{PAGE_MODULE}.tell")
    window.open_section(0)

    window.forms_page.print_form()

    assert window.stack.currentWidget() is window.organization_page


def test_printing_a_version_again_draws_from_its_first_printing(
    page: FormsPage,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    tmp_path: Path,
) -> None:
    mocker.patch(f"{PAGE_MODULE}.choose_pdf_path", return_value=tmp_path / "a.pdf")
    page.export_pdf()
    (form,) = list_forms(connection)
    stored = load_printed_layout(connection, form.form_id, form.version)
    assert stored is not None
    first = thawed_layout(stored[FROZEN_LAYOUT_KEY], form)
    save = mocker.patch(f"{PAGE_MODULE}.save_pdf", return_value=2)

    page.export_pdf()

    assert first is not None
    assert save.call_args.args[4] == first


def test_a_reprint_without_its_typeface_says_it_still_scans(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_organization(connection, ORGANIZATION)
    form = save_form(connection, intake(font=FormFont(family="No Such Typeface")))
    layout = layout_form(form, ORGANIZATION.paper_size)
    mark_printed(connection, form.form_id, form.version, printed_layout(layout))
    editor = FormsPage(connection)
    qtbot.addWidget(editor)
    confirm = mocker.patch(
        f"{PAGE_MODULE}.confirm_despite_problems", return_value=False
    )
    choose = mocker.patch(f"{PAGE_MODULE}.choose_pdf_path")

    editor.export_pdf()

    (warning,) = confirm.call_args.args[2]
    assert "No Such Typeface" in warning
    assert "sheets still scan the same" in warning
    choose.assert_not_called()
