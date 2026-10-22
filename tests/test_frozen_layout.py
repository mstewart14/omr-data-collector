from __future__ import annotations

import json
import math
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtGui import QFontDatabase

from omr_data_collector.constants import PAPER_SIZES
from omr_data_collector.engine.scanning import scan_sheet
from omr_data_collector.layout import frozen_layout as frozen_layout_module
from omr_data_collector.layout import text
from omr_data_collector.layout.form_layout import layout_form
from omr_data_collector.layout.frozen_layout import (
    FROZEN_LAYOUT_KEY,
    frozen_layout,
    frozen_warnings,
    layout_to_print,
    printed_layout,
    thawed_layout,
)
from omr_data_collector.layout.text import fitted_document, markdown_document
from omr_data_collector.models.FormFont import FormFont
from omr_data_collector.storage.form_store import (
    load_printed_layout,
    mark_printed,
    save_form,
)
from tests.sheets import LETTER, Sheet, intake_form

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from omr_data_collector.layout.form_layout import FormLayout
    from omr_data_collector.models.Form import Form
    from omr_data_collector.models.Organization import Organization

pytestmark = pytest.mark.usefixtures("qapp")


def serif() -> str:
    """An installed family unlike the standard one, to print the form in."""
    for family in ("DejaVu Serif", "Noto Serif", "Liberation Serif", "Georgia"):
        if QFontDatabase.hasFamily(family):
            return family
    pytest.skip("no serif font is installed")
    return ""


def bubbles(layout: FormLayout) -> list[tuple[int, float, float]]:
    """Every question bubble's block and place on the page."""
    return [
        (placed.index, bubble.centre_x_mm, placed.y_mm + bubble.centre_y_mm)
        for page in layout.pages
        for placed in page.blocks
        if placed.question is not None
        for bubble in placed.question.bubbles
    ]


def print_version(
    connection: sqlite3.Connection, organization: Organization, font: FormFont
) -> tuple[Form, FormLayout]:
    """Save the intake form in ``font`` and print it, as the first printing does."""
    form = save_form(connection, replace(intake_form(), font=font))
    layout = layout_form(form, organization.paper_size)
    mark_printed(connection, form.form_id, form.version, printed_layout(layout))
    return form, layout


@pytest.fixture
def without_the_serif(monkeypatch: pytest.MonkeyPatch) -> str:
    """Another computer: the form's serif isn't there, so a sans takes its place."""
    family = serif()
    standard = text.form_family

    def substitute(font: FormFont) -> str:
        return "DejaVu Sans" if font.family == family else standard(font)

    monkeypatch.setattr(text, "form_family", substitute)
    monkeypatch.setattr(
        frozen_layout_module, "has_family", lambda font: font.family != family
    )
    return family


# --- Storing and reading back ---------------------------------------------------


@pytest.mark.parametrize(
    "font",
    [FormFont(), FormFont(size=14), "serif"],
    ids=["standard", "14 pt", "serif"],
)
def test_the_whole_layout_reads_back_as_it_was(font: FormFont | str) -> None:
    chosen = FormFont(family=serif(), size=12) if font == "serif" else font
    assert isinstance(chosen, FormFont)
    form = replace(intake_form(), font=chosen)
    layout = layout_form(form, LETTER)

    stored = json.loads(json.dumps(printed_layout(layout)))

    assert thawed_layout(stored[FROZEN_LAYOUT_KEY], form) == layout


def test_a_placed_block_is_its_forms_own() -> None:
    form = intake_form()
    stored = frozen_layout(layout_form(form, LETTER))

    thawed = thawed_layout(stored, form)

    assert thawed is not None
    for placed in thawed.pages[0].blocks:
        assert placed.block is form.blocks[placed.index]


def table_part(stored: dict[str, Any]) -> dict[str, Any]:
    """The stored layout's first table part."""
    return next(
        placed["table_part"]
        for page in stored["pages"]
        for placed in page["blocks"]
        if placed["table_part"] is not None
    )


def damaged(change: str) -> object:
    stored = frozen_layout(layout_form(intake_form(), LETTER))
    first = stored["pages"][0]["blocks"][0]
    if change == "not an object":
        return []
    if change == "missing a field":
        del stored["width_mm"]
    elif change == "text for a number":
        stored["width_mm"] = "wide"
    elif change == "true for a number":
        stored["width_mm"] = True
    elif change == "not a number":
        stored["width_mm"] = math.nan
    elif change == "far off the page":
        first["y_mm"] = 1e9
    elif change == "a block the form hasn't":
        first["index"] = 99
    elif change == "no pages":
        stored["pages"] = []
    elif change == "a bubble that isn't one":
        first["question"]["bubbles"] = [{"centre_x_mm": 1}]
    return stored


@pytest.mark.parametrize(
    "change",
    [
        "not an object",
        "missing a field",
        "text for a number",
        "true for a number",
        "not a number",
        "far off the page",
        "a block the form hasn't",
        "no pages",
        "a bubble that isn't one",
    ],
)
def test_a_damaged_or_crafted_layout_is_ignored(change: str) -> None:
    assert thawed_layout(damaged(change), intake_form()) is None


@pytest.mark.parametrize(
    "change",
    ["another font", "a table in another font", "a column more", "a column short"],
)
def test_a_layout_that_doesnt_fit_its_form_is_ignored(change: str) -> None:
    # Each would otherwise stop printing part way, or print what doesn't scan.
    stored = frozen_layout(layout_form(intake_form(), LETTER))
    table = table_part(stored)["layout"]
    if change == "another font":
        stored["font"]["size"] = 9000.0
    elif change == "a table in another font":
        table["font"]["family"] = "Serif"
    elif change == "a column more":
        table["columns"].append(table["columns"][0])
    else:
        table["columns"].pop()

    assert thawed_layout(stored, intake_form()) is None


# --- Which layout prints ----------------------------------------------------------


def test_a_version_not_yet_printed_is_laid_out_now() -> None:
    form = intake_form()

    layout, frozen = layout_to_print(form, LETTER, None)

    assert not frozen
    assert layout == layout_form(form, LETTER)


def test_a_printed_version_prints_from_its_first_printing(
    connection: sqlite3.Connection, organization: Organization
) -> None:
    form, first = print_version(connection, organization, FormFont(size=12))

    stored = load_printed_layout(connection, form.form_id, form.version)
    layout, frozen = layout_to_print(form, LETTER, stored)

    assert frozen
    assert layout == first


def test_versions_printed_before_layouts_were_kept_are_laid_out_now(
    connection: sqlite3.Connection, organization: Organization
) -> None:
    form, first = print_version(connection, organization, FormFont())
    stored = load_printed_layout(connection, form.form_id, form.version)
    assert stored is not None
    del stored[FROZEN_LAYOUT_KEY]

    layout, frozen = layout_to_print(form, LETTER, stored)

    assert not frozen
    assert layout == first


def test_a_layout_with_other_pages_than_its_templates_is_laid_out_now(
    connection: sqlite3.Connection, organization: Organization
) -> None:
    form, _ = print_version(connection, organization, FormFont())
    stored = load_printed_layout(connection, form.form_id, form.version)
    assert stored is not None
    stored["pages"].append(stored["pages"][0])

    _, frozen = layout_to_print(form, LETTER, stored)

    assert not frozen


def test_other_paper_is_laid_out_for_that_paper(
    connection: sqlite3.Connection, organization: Organization
) -> None:
    form, _ = print_version(connection, organization, FormFont())
    stored = load_printed_layout(connection, form.form_id, form.version)

    layout, frozen = layout_to_print(form, PAPER_SIZES.A4, stored)

    assert not frozen
    assert layout == layout_form(form, PAPER_SIZES.A4)


# --- Printing on a computer without the form's typeface -------------------------


def test_without_the_typeface_a_fresh_layout_would_move_the_bubbles(
    connection: sqlite3.Connection,
    organization: Organization,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    family = serif()
    form, first = print_version(connection, organization, FormFont(family=family))
    standard = text.form_family
    monkeypatch.setattr(
        text,
        "form_family",
        lambda font: "DejaVu Sans" if font.family == family else standard(font),
    )

    assert bubbles(layout_form(form, organization.paper_size)) != bubbles(first)


def test_a_reprint_without_the_typeface_still_scans(
    connection: sqlite3.Connection,
    organization: Organization,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Printed first where the serif is installed...
    family = serif()
    form, first = print_version(connection, organization, FormFont(family=family))
    # ...and again where it isn't.
    standard = text.form_family
    monkeypatch.setattr(
        text,
        "form_family",
        lambda font: "DejaVu Sans" if font.family == family else standard(font),
    )
    stored = load_printed_layout(connection, form.form_id, form.version)
    layout, frozen = layout_to_print(form, organization.paper_size, stored)
    assert frozen
    assert bubbles(layout) == bubbles(first)
    sheet = Sheet(form, organization, layout)
    sheet.fill_question(1, 0, 3)
    sheet.fill_cell(2, row=0, column=2, choice=2)

    page = scan_sheet(connection, sheet.photograph(tmp_path / "photo.jpg"), LETTER)

    answers = {
        (answer.block_index, answer.table_row, answer.column): answer.values
        for answer in page.answers
    }
    assert answers[1, None, None] == ("food", "other")
    assert answers[2, 0, 2] == ("referral",)
    assert all(not answer.problem for answer in page.answers)


def test_a_missing_typeface_only_warns_for_a_frozen_layout(
    without_the_serif: str,
) -> None:
    layout = layout_form(
        replace(intake_form(), font=FormFont(family=without_the_serif)), LETTER
    )

    (warning,) = frozen_warnings(layout, 3)

    assert without_the_serif in warning
    assert "version 3" in warning
    assert frozen_warnings(layout_form(intake_form(), LETTER), 3) == ()


# --- Fitting text into stored room ------------------------------------------------


def test_text_that_fits_is_drawn_as_it_is() -> None:
    font = FormFont()
    document = markdown_document("Welcome to the food bank.", 100, 10, font=font)
    height = document.size().height() * text.MM_PER_POINT

    fitted = fitted_document(
        lambda font: markdown_document("Welcome to the food bank.", 100, 10, font=font),
        font,
        height,
    )

    assert fitted.defaultFont().pointSizeF() == document.defaultFont().pointSizeF()


def test_text_taller_than_its_room_shrinks_to_fit() -> None:
    words = "Please answer every question on both sides of this sheet. " * 6
    font = FormFont()
    full = text.document_height_mm(markdown_document(words, 60, 10, font=font))

    fitted = fitted_document(
        lambda font: markdown_document(words, 60, 10, font=font), font, full * 0.7
    )

    assert text.document_height_mm(fitted) <= full * 0.7
    assert fitted.defaultFont().pointSizeF() < 10


def test_a_layout_stored_before_headings_wrapped_still_prints() -> None:
    form = intake_form()
    stored = frozen_layout(layout_form(form, LETTER))
    for page in stored["pages"]:
        for placed in page["blocks"]:
            if placed["table_part"] is not None:
                for column in placed["table_part"]["layout"]["columns"]:
                    del column["heading_lines"]

    thawed = thawed_layout(stored, form)

    assert thawed is not None
    (table,) = [p for p in thawed.pages[0].blocks if p.table_part is not None]
    assert table.table_part is not None
    assert all(not column.heading_lines for column in table.table_part.layout.columns)
