from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import jsonschema
import pytest
from PySide6.QtGui import QFont, QFontDatabase

from omr_data_collector.engine.scanning import scan_sheet
from omr_data_collector.layout.form_layout import (
    HEADER_HEIGHT_MM,
    layout_form,
    question_geometry,
)
from omr_data_collector.layout.omr_template import printed_layout
from omr_data_collector.layout.table_layout import table_layout
from omr_data_collector.layout.text import (
    has_family,
    standard_family,
    text_font,
    text_width_mm,
)
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.FormFont import STANDARD_SIZE, FormFont
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.storage.form_store import list_forms, mark_printed, save_form
from omr_data_collector.ui.font_choices import (
    family_choices,
    size_choices,
    style_choices,
)
from omr_data_collector.ui.FormsPage import FormsPage
from tests.sheets import LETTER, Sheet, intake_form

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from pytestqt.qtbot import QtBot

    from omr_data_collector.models.Organization import Organization

pytestmark = pytest.mark.usefixtures("qapp")

MISSING = "No Such Typeface 7f3a"


def other_family() -> str:
    """An installed family that isn't the standard one, preferring a serif."""
    families = [
        family
        for family in QFontDatabase.families()
        if family != standard_family() and not QFontDatabase.isPrivateFamily(family)
    ]
    for preferred in ("DejaVu Serif", "Noto Serif", "Liberation Serif", "Georgia"):
        if preferred in families:
            return preferred
    if not families:
        pytest.skip("only one font is installed")
    return families[0]


def prompt_question(
    prompt: str = "How many people live in your household?",
) -> Question:
    question = intake_form().blocks[1].content
    assert isinstance(question, Question)
    return replace(question, prompt=prompt)


# --- The model ----------------------------------------------------------------


def test_a_standard_form_keeps_its_definition_as_before() -> None:
    form = intake_form()

    assert form.font.is_standard()
    assert "font" not in form.definition()


def test_a_chosen_font_is_stored_and_read_back() -> None:
    font = FormFont(family="DejaVu Serif", style="Light", size=12)
    form = replace(intake_form(), font=font)

    read = Form.from_definition(form.definition(), form_id=form.form_id, version=1)

    assert form.definition()["font"] == {
        "family": "DejaVu Serif",
        "style": "Light",
        "size": 12,
    }
    assert read.font == font


def test_a_definition_from_before_fonts_reads_as_standard() -> None:
    form = intake_form()

    read = Form.from_definition(form.definition(), form_id=form.form_id, version=1)

    assert read.font == FormFont()


def test_a_damaged_font_is_refused() -> None:
    definition = intake_form().definition()
    definition["font"] = {"family": "Serif", "size": 12}

    with pytest.raises(jsonschema.ValidationError):
        Form.from_definition(definition, form_id="a" * 32, version=1)


@pytest.mark.parametrize("size", [7, 15])
def test_text_sizes_outside_the_range_are_refused(size: float) -> None:
    form = replace(intake_form(), font=FormFont(size=size))

    assert "font_size" in form.validation_errors(set())


def test_saving_keeps_the_font(connection: sqlite3.Connection) -> None:
    font = FormFont(family=other_family(), size=12)
    save_form(connection, replace(intake_form(), font=font))

    (saved,) = list_forms(connection)

    assert saved.font == font


# --- Measuring and drawing ------------------------------------------------------


def test_text_is_drawn_in_the_forms_typeface() -> None:
    family = other_family()

    assert text_font(FormFont(family=family)).family() == family
    assert text_font(FormFont()).family() == standard_family()


def test_bold_and_italic_still_apply_over_a_style() -> None:
    family, light = next(
        (
            (family, style)
            for family in QFontDatabase.families()
            for style in QFontDatabase.styles(family)
            if style == "Light"
        ),
        (None, None),
    )
    if family is None or light is None:
        pytest.skip("no installed font has a light style")
    font = FormFont(family=family, style=light)

    assert text_font(font).weight() < QFont.Weight.Normal
    assert text_font(font, bold=True).weight() == QFont.Weight.Bold
    assert text_font(font, italic=True).italic()


def test_a_bigger_size_scales_text() -> None:
    standard = text_width_mm("Household", 10, font=FormFont())
    bigger = text_width_mm("Household", 10, font=FormFont(size=12))

    assert bigger == pytest.approx(standard * 1.2, rel=0.01)


def test_another_typeface_measures_differently() -> None:
    text = "Number of people in the household"
    standard = text_width_mm(text, 10, font=FormFont())

    other = text_width_mm(text, 10, font=FormFont(family=other_family()))

    assert other != pytest.approx(standard, rel=0.001)


def test_bigger_text_makes_questions_taller_and_choices_wider() -> None:
    question = prompt_question()

    standard = question_geometry(question, 80)
    bigger = question_geometry(question, 80, font=FormFont(size=14))

    assert bigger.prompt_height_mm > standard.prompt_height_mm
    assert bigger.choice_pitch_mm > standard.choice_pitch_mm


def test_table_columns_fit_their_headings_in_the_forms_font() -> None:
    table = intake_form().blocks[2].content

    standard = table_layout(table)  # pyright: ignore[reportArgumentType]
    bigger = table_layout(table, font=FormFont(size=14))  # pyright: ignore[reportArgumentType]

    assert bigger.width_mm > standard.width_mm
    assert bigger.header_height_mm > standard.header_height_mm
    assert bigger.font == FormFont(size=14)


def test_the_header_keeps_its_height_whatever_the_size() -> None:
    form = replace(intake_form(), font=FormFont(size=14))

    layout = layout_form(form, LETTER)

    assert layout.header_height_mm == HEADER_HEIGHT_MM
    assert layout.font == form.font


def test_a_missing_typeface_is_a_problem_to_check_before_printing() -> None:
    form = replace(intake_form(), font=FormFont(family=MISSING))

    layout = layout_form(form, LETTER)

    assert not has_family(form.font)
    assert any(MISSING in warning for warning in layout.warnings)


@pytest.mark.parametrize(
    "font",
    [FormFont(size=14), FormFont(size=8), "other"],
    ids=["14 pt", "8 pt", "another typeface"],
)
def test_forms_in_any_font_scan_back(
    connection: sqlite3.Connection,
    organization: Organization,
    tmp_path: Path,
    font: FormFont | str,
) -> None:
    chosen = FormFont(family=other_family(), size=12) if font == "other" else font
    assert isinstance(chosen, FormFont)
    form = save_form(connection, replace(intake_form(), font=chosen))
    layout = layout_form(form, organization.paper_size)
    mark_printed(connection, form.form_id, form.version, printed_layout(layout))
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


# --- The choices ------------------------------------------------------------------


def test_the_standard_font_is_offered_first_then_every_family() -> None:
    choices = family_choices("")

    assert choices[0] == (f"Standard font ({standard_family()})", "")
    assert (other_family(), other_family()) in choices


def test_a_missing_family_stays_on_the_list_marked() -> None:
    choices = family_choices(MISSING)

    assert (f"{MISSING} (not installed)", MISSING) in choices


def test_styles_start_with_regular() -> None:
    choices = style_choices("", "")

    assert choices[0] == ("Regular", "")
    assert all(label.casefold() != "regular" for label, _ in choices[1:])


def test_sizes_include_the_forms_own() -> None:
    assert ("10.5 pt", 10.5) in size_choices(10.5)
    assert [size for _, size in size_choices(10)] == [8, 9, 10, 11, 12, 13, 14]


# --- The form details -----------------------------------------------------------


@pytest.fixture
def page(qtbot: QtBot, connection: sqlite3.Connection) -> FormsPage:
    save_form(
        connection,
        Form(
            name="Intake",
            blocks=(FormBlock(TextBlock(name="A", content="Welcome")),),
        ).normalized(),
    )
    editor = FormsPage(connection)
    qtbot.addWidget(editor)
    return editor


def choose(combo, value: object) -> None:
    index = combo.findData(value)
    assert index >= 0, value
    combo.setCurrentIndex(index)


def test_a_new_form_starts_in_the_standard_font(page: FormsPage) -> None:
    assert page.chosen_font() == FormFont()
    assert page.font_size_combo.currentText() == "10 pt"


def test_choosing_a_font_is_saved_with_the_form(
    page: FormsPage, connection: sqlite3.Connection
) -> None:
    family = other_family()
    choose(page.family_combo, family)
    choose(page.font_size_combo, 12.0)

    assert page.has_unsaved_changes()
    assert page.canvas.form_layout is not None
    assert page.canvas.form_layout.font == FormFont(family=family, size=12)
    assert page.save()
    (saved,) = list_forms(connection)
    assert saved.font == FormFont(family=family, size=12)


def test_a_new_typeface_starts_at_its_regular_style(page: FormsPage) -> None:
    styles = [value for _, value in style_choices("", "") if value]
    if not styles:
        pytest.skip("the standard font has only one style here")
    choose(page.style_combo, styles[0])

    choose(page.family_combo, other_family())

    assert page.style_combo.currentData() == ""


def test_font_changes_can_be_undone(page: FormsPage) -> None:
    choose(page.font_size_combo, 14.0)
    choose(page.family_combo, other_family())

    page.undo()
    assert page.chosen_font() == FormFont(size=14)
    page.undo()
    assert page.chosen_font() == FormFont()
    assert not page.has_unsaved_changes()


def test_a_form_in_a_missing_typeface_keeps_it(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    font = FormFont(family=MISSING, size=STANDARD_SIZE)
    save_form(connection, replace(intake_form(), font=font))
    editor = FormsPage(connection)
    qtbot.addWidget(editor)

    assert editor.family_combo.currentText() == f"{MISSING} (not installed)"
    assert editor.chosen_font() == font
    assert not editor.has_unsaved_changes()
    assert MISSING in editor.problems_note.text()


def test_a_copy_keeps_the_font(page: FormsPage) -> None:
    form = replace(page.read_item("Intake", "a" * 32), font=FormFont(size=12))

    assert page.copy_item(form, "Intake copy").font == FormFont(size=12)
