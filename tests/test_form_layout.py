from __future__ import annotations

import pytest

from omr_data_collector.constants import (
    ANSWER_TYPES,
    PAGE_ORIENTATIONS,
    PAPER_SIZES,
    TABLE_BREAKS,
    WRITTEN_DATA_TYPES,
)
from omr_data_collector.layout.form_layout import (
    BLOCK_GAP_MM,
    CONTENT_TOP_MM,
    layout_form,
    question_geometry,
)
from omr_data_collector.layout.markers import marker_centres_mm
from omr_data_collector.layout.table_layout import WRITTEN_BOX_WIDTH_MM
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.models.TextBlock import TextBlock

# Measuring text needs Qt's font system, which needs an application.
pytestmark = pytest.mark.usefixtures("qapp")

LETTER = PAPER_SIZES.LETTER


def text(name: str = "Title", content: str = "# Client intake") -> FormBlock:
    return FormBlock(TextBlock(name=name, content=content))


def question(name: str = "visit", *labels: str) -> FormBlock:
    return FormBlock(
        Question(
            name=name,
            prompt="Is this your first visit?",
            answer=AnswerSpec(
                ANSWER_TYPES.ONE_CHOICE if len(labels) > 2 else ANSWER_TYPES.YES_NO,
                choices=tuple(
                    Choice(label, label) for label in (labels or ("Yes", "No"))
                ),
            ),
        )
    )


def table(rows: int = 10, **block_options: object) -> FormBlock:
    return FormBlock(
        TableBlock(
            name="Visit log",
            rows=rows,
            fill_page=bool(block_options.pop("fill_page", False)),
            columns=(
                Column(
                    "time", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=5)
                ),
            ),
        ),
        **block_options,  # type: ignore[arg-type]
    )


def form(*blocks: FormBlock, orientation: str = PAGE_ORIENTATIONS.PORTRAIT) -> Form:
    return Form(name="Intake", orientation=orientation, blocks=blocks)


def placed(layout, page: int = 1):
    return layout.pages[page - 1].blocks


def test_blocks_stack_in_order_below_the_header() -> None:
    layout = layout_form(form(text(), question(), text("Footer", "Thanks")), LETTER)

    (page,) = layout.pages
    first, second, third = page.blocks
    assert first.y_mm == CONTENT_TOP_MM
    assert second.y_mm == pytest.approx(first.y_mm + first.height_mm + BLOCK_GAP_MM)
    assert third.y_mm == pytest.approx(second.y_mm + second.height_mm + BLOCK_GAP_MM)
    assert [block.index for block in page.blocks] == [0, 1, 2]


def test_landscape_pages_are_wider() -> None:
    portrait = layout_form(form(text()), LETTER)
    landscape = layout_form(
        form(text(), orientation=PAGE_ORIENTATIONS.LANDSCAPE), LETTER
    )

    assert landscape.width_mm > portrait.width_mm
    assert landscape.height_mm < portrait.height_mm


def test_a_block_can_start_a_new_page() -> None:
    layout = layout_form(
        form(text(), FormBlock(text().content, start_on_new_page=True)), LETTER
    )

    assert len(layout.pages) == 2
    assert placed(layout, 2)[0].y_mm == CONTENT_TOP_MM


def test_start_on_new_page_does_nothing_at_the_top_of_a_page() -> None:
    layout = layout_form(
        form(FormBlock(text().content, start_on_new_page=True)), LETTER
    )

    assert len(layout.pages) == 1


def test_text_that_does_not_fit_moves_down_whole() -> None:
    long_text = "\n\n".join(f"Paragraph {n}." for n in range(60))
    layout = layout_form(form(text(), text("Long", long_text)), LETTER)

    assert [len(page.blocks) for page in layout.pages] == [1, 1]
    assert placed(layout, 2)[0].block.content.name == "Long"


def test_a_long_table_splits_with_its_heading_on_each_page() -> None:
    layout = layout_form(form(text(), table(rows=50)), LETTER)

    parts = [
        block.table_part
        for page in layout.pages
        for block in page.blocks
        if block.table_part
    ]
    assert len(parts) == 2
    assert sum(part.row_count for part in parts) == 50
    assert parts[0].first_row == 0
    assert parts[1].first_row == parts[0].row_count
    assert parts[1].continued
    assert parts[1].instructions_height_mm == 0


def test_a_table_set_to_move_starts_a_new_page_rather_than_split() -> None:
    first = layout_form(form(text(), question(), table(rows=24)), LETTER)
    rows_left_on_page_one = sum(
        block.table_part.row_count for block in placed(first) if block.table_part
    )
    assert 0 < rows_left_on_page_one < 24  # it would split

    moved = layout_form(
        form(text(), question(), table(rows=24, table_break=TABLE_BREAKS.NEW_PAGE)),
        LETTER,
    )

    assert [block.table_part for block in placed(moved) if block.table_part] == []
    (table_part,) = [block.table_part for block in placed(moved, 2)]
    assert table_part is not None
    assert table_part.row_count == 24


def test_a_table_too_long_for_any_page_splits_even_when_set_to_move() -> None:
    layout = layout_form(
        form(text(), table(rows=50, table_break=TABLE_BREAKS.NEW_PAGE)), LETTER
    )

    parts = [
        block.table_part
        for page in layout.pages
        for block in page.blocks
        if block.table_part
    ]
    assert sum(part.row_count for part in parts) == 50
    assert len(parts) >= 2


def test_filling_tables_take_the_rows_that_fit_below_them() -> None:
    alone = layout_form(form(table(fill_page=True)), LETTER)
    below_text = layout_form(form(text(), question(), table(fill_page=True)), LETTER)

    (alone_part,) = [block.table_part for block in placed(alone)]
    (lower_part,) = [
        block.table_part for block in placed(below_text) if block.table_part
    ]
    assert alone_part is not None
    assert lower_part is not None
    assert alone_part.row_count > lower_part.row_count > 0
    last = placed(below_text)[-1]
    assert last.y_mm + last.height_mm <= below_text.height_mm


def test_question_choices_wrap_onto_new_rows() -> None:
    labels = [f"A fairly long choice label {n}" for n in range(8)]
    geometry = question_geometry(
        question("q", *labels).content,  # type: ignore[arg-type]
        width_mm=100,
    )

    rows = {bubble.centre_y_mm for bubble in geometry.bubbles}
    assert len(rows) > 1
    assert all(bubble.centre_x_mm < 100 for bubble in geometry.bubbles)
    assert [bubble.choice_index for bubble in geometry.bubbles] == list(range(8))


def test_numbers_get_one_box_per_digit_wrapping_if_needed() -> None:
    written = Question(
        name="client_number",
        prompt="Client number",
        answer=AnswerSpec(
            ANSWER_TYPES.WRITTEN, data_type=WRITTEN_DATA_TYPES.NUMBER, max_characters=30
        ),
    )

    geometry = question_geometry(written, width_mm=100)

    assert len(geometry.boxes) == 30
    assert all(box.printed == "" for box in geometry.boxes)
    per_row = int(100 // WRITTEN_BOX_WIDTH_MM)
    assert len({box.y_mm for box in geometry.boxes}) == -(-30 // per_row)
    assert geometry.lines == ()


def test_free_text_gets_writing_lines_not_boxes() -> None:
    written = Question(
        name="notes",
        prompt="Notes",
        answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=30),
    )

    geometry = question_geometry(written, width_mm=100)

    assert geometry.boxes == ()
    # 30 characters' worth of line: one full line, then the rest.
    assert [line.width_mm for line in geometry.lines] == [
        100,
        30 * WRITTEN_BOX_WIDTH_MM - 100,
    ]
    assert geometry.height_mm > geometry.lines[-1].y_mm


@pytest.mark.parametrize(
    ("date_time_format", "pattern"),
    [
        ("HH:MM", "[][]:[][]"),
        ("YYYY/MM/DD", "[][][][]/[][]/[][]"),
        ("YYYY/MM/DD HH:MM", "[][][][]/[][]/[][] [][]:[][]"),
    ],
)
def test_dates_and_times_print_their_separators_between_boxes(
    date_time_format: str, pattern: str
) -> None:
    written = Question(
        name="when",
        prompt="When?",
        answer=AnswerSpec(
            ANSWER_TYPES.WRITTEN,
            data_type=WRITTEN_DATA_TYPES.DATE_TIME,
            date_time_format=date_time_format,
        ),
    )

    geometry = question_geometry(written, width_mm=180)

    assert "".join(box.printed or "[]" for box in geometry.boxes) == pattern


def test_warns_about_a_table_too_wide_for_the_page() -> None:
    wide = FormBlock(
        TableBlock(
            name="Wide",
            columns=tuple(
                Column(
                    f"c{n}", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=6)
                )
                for n in range(8)
            ),
        )
    )

    layout = layout_form(form(wide), LETTER)

    assert layout.warnings == (
        'The table "Wide" is 264 mm wide but the page has 191 mm.',
    )


def test_question_choices_are_evenly_spaced_for_omr() -> None:
    geometry = question_geometry(
        question("q", "A", "A much longer label", "B").content,  # type: ignore[arg-type]
        width_mm=180,
    )

    xs = [bubble.centre_x_mm for bubble in geometry.bubbles]
    assert xs[1] - xs[0] == pytest.approx(geometry.choice_pitch_mm)
    assert xs[2] - xs[1] == pytest.approx(geometry.choice_pitch_mm)


def test_the_layout_knows_the_whole_sheet_for_the_corner_markers() -> None:
    layout = layout_form(form(text()), LETTER)

    assert layout.paper_width_mm == pytest.approx(215.9, abs=0.1)
    assert layout.paper_height_mm == pytest.approx(279.4, abs=0.1)
    (left, top), _, (right, bottom), _ = marker_centres_mm(
        layout.paper_width_mm, layout.paper_height_mm
    )
    # Out in the margins, clear of the printable area.
    assert left < 0
    assert top < 0
    assert right > layout.width_mm
    assert bottom > layout.height_mm
