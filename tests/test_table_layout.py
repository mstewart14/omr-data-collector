from __future__ import annotations

from dataclasses import replace

import pytest

from omr_data_collector.constants import (
    ANSWER_TYPES,
    PAGE_ORIENTATIONS,
    PAPER_SIZES,
    WRITTEN_DATA_TYPES,
)
from omr_data_collector.layout.table_layout import (
    BUBBLE_PITCH_MM,
    CELL_PADDING_MM,
    WRITTEN_BOX_WIDTH_MM,
    cell_bubble_centres_mm,
    cell_written_marks_mm,
    column_layout,
    rows_to_print,
    table_layout,
    text_width_mm,
)
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.FormFont import FormFont
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.ui.TablePreview import fit_summary

# Text measurement needs Qt's font system, which needs an application.
pytestmark = pytest.mark.usefixtures("qapp")


def choices(*labels: str) -> tuple[Choice, ...]:
    return tuple(Choice(label, label) for label in labels)


def test_written_column_is_one_box_per_character() -> None:
    column = Column("id", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=8))

    layout = column_layout(column)

    assert layout.width_mm == pytest.approx(
        8 * WRITTEN_BOX_WIDTH_MM + 2 * CELL_PADDING_MM
    )
    assert layout.choice_pitch_mm == 0


def test_date_column_is_sized_by_its_format() -> None:
    column = Column(
        "d",
        answer=AnswerSpec(
            ANSWER_TYPES.WRITTEN,
            data_type=WRITTEN_DATA_TYPES.DATE_TIME,
            date_time_format="YYYY/MM/DD",
        ),
    )

    assert column_layout(column).width_mm == pytest.approx(
        10 * WRITTEN_BOX_WIDTH_MM + 2 * CELL_PADDING_MM
    )


def test_short_choice_labels_use_the_standard_bubble_pitch() -> None:
    column = Column(
        "v", answer=AnswerSpec(ANSWER_TYPES.ONE_CHOICE, choices=choices("Y", "N"))
    )

    layout = column_layout(column)

    assert layout.choice_pitch_mm == BUBBLE_PITCH_MM
    assert layout.width_mm == pytest.approx(2 * BUBBLE_PITCH_MM + 2 * CELL_PADDING_MM)


def test_long_choice_labels_widen_the_pitch() -> None:
    column = Column(
        "s",
        answer=AnswerSpec(
            ANSWER_TYPES.ONE_CHOICE, choices=choices("Emergency shelter", "B", "C")
        ),
    )

    assert column_layout(column).choice_pitch_mm > BUBBLE_PITCH_MM


def test_a_column_is_never_narrower_than_its_name() -> None:
    name = "number_of_people_in_household"
    column = Column(name, answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=1))

    assert column_layout(column).width_mm >= text_width_mm(
        name, 8, font=FormFont(), bold=True
    )


def test_table_width_is_the_sum_of_its_columns() -> None:
    columns = (
        Column("a", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=4)),
        Column("b", answer=AnswerSpec(ANSWER_TYPES.YES_NO, choices=choices("Y", "N"))),
    )
    layout = table_layout(TableBlock(name="t", rows=5, columns=columns))

    assert layout.width_mm == pytest.approx(
        sum(column_layout(column).width_mm for column in columns)
    )
    assert layout.height_mm == pytest.approx(
        layout.header_height_mm + 5 * layout.row_height_mm
    )


def wide_table(rows: int = 10) -> TableBlock:
    # Ten 4-character written columns: about 230 mm, wider than portrait Letter.
    return TableBlock(
        name="t",
        rows=rows,
        columns=tuple(
            Column(f"c{n}", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=4))
            for n in range(10)
        ),
    )


def test_summary_says_when_a_table_fits() -> None:
    table = TableBlock(
        name="t",
        rows=5,
        columns=(
            Column("a", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=4)),
        ),
    )

    summary = fit_summary(table, PAPER_SIZES.LETTER, PAGE_ORIENTATIONS.PORTRAIT)

    assert summary.startswith("Fits on Letter portrait: 23 of 191 mm wide.")


def test_summary_says_how_much_too_wide_and_what_to_try() -> None:
    portrait = fit_summary(wide_table(), PAPER_SIZES.LETTER, PAGE_ORIENTATIONS.PORTRAIT)
    landscape = fit_summary(
        wide_table(), PAPER_SIZES.LETTER, PAGE_ORIENTATIONS.LANDSCAPE
    )

    assert portrait.startswith("Too wide for Letter portrait: the table is 230 mm wide")
    assert "Try landscape" in portrait
    assert landscape.startswith("Fits on Letter landscape")


def test_summary_counts_pages_when_rows_overflow() -> None:
    summary = fit_summary(
        wide_table(rows=50), PAPER_SIZES.A4, PAGE_ORIENTATIONS.LANDSCAPE
    )

    assert "rows fit on a page, so the table takes 3 pages." in summary


def test_summary_for_a_table_without_columns() -> None:
    summary = fit_summary(
        TableBlock(name="t"), PAPER_SIZES.A4, PAGE_ORIENTATIONS.PORTRAIT
    )

    assert summary == "Add columns to preview the table on A4 portrait."


def test_fixed_tables_print_their_row_count_wherever_they_are() -> None:
    table = wide_table(rows=7)

    assert rows_to_print(table, 500) == 7
    assert rows_to_print(table, 20) == 7


def test_filled_tables_print_every_row_that_fits_below_them() -> None:
    table = replace(wide_table(), fill_page=True)
    header = table_layout(table).header_height_mm

    assert rows_to_print(table, header + 8 * 10) == 10
    assert rows_to_print(table, header + 8 * 10 - 1) == 9
    assert rows_to_print(table, header - 1) == 0


def test_summary_explains_that_filled_rows_depend_on_placement() -> None:
    table = replace(wide_table(), fill_page=True)

    summary = fit_summary(table, PAPER_SIZES.LETTER, PAGE_ORIENTATIONS.LANDSCAPE)

    assert "Fills the page:" in summary
    assert (
        "rows on Letter landscape when the table starts at the top of a page" in summary
    )
    assert "fewer if it's placed lower on a form." in summary


def test_free_text_table_cells_are_left_open_to_write_in() -> None:
    column = Column("notes", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=12))

    assert cell_written_marks_mm(column, column_layout(column)) == []
    assert column_layout(column).width_mm == pytest.approx(
        12 * WRITTEN_BOX_WIDTH_MM + 2 * CELL_PADDING_MM
    )


def test_time_table_cells_box_the_digits_around_a_printed_colon() -> None:
    column = Column(
        "time",
        answer=AnswerSpec(
            ANSWER_TYPES.WRITTEN,
            data_type=WRITTEN_DATA_TYPES.DATE_TIME,
            date_time_format="HH:MM",
        ),
    )

    marks = cell_written_marks_mm(column, column_layout(column))

    assert [printed for _, printed in marks] == ["", "", ":", "", ""]
    lefts = [left for left, _ in marks]
    assert lefts == sorted(lefts)


def test_a_yes_no_column_has_one_bubble_per_cell() -> None:
    column = Column(
        "first", answer=AnswerSpec(ANSWER_TYPES.YES_NO, choices=choices("Y", "N"))
    )

    assert len(cell_bubble_centres_mm(column, column_layout(column))) == 1
