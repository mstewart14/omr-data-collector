"""Sizes of a table block on paper, in millimetres.

The preview uses this now; printing and the OMRChecker template will use the same
numbers, so what is previewed is what is printed and scanned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from omr_data_collector.constants import ANSWER_TYPES
from omr_data_collector.layout.text import (  # noqa: F401 (MM_PER_POINT re-exported)
    MM_PER_POINT,
    line_height_mm,
    text_width_mm,
)
from omr_data_collector.models.AnswerSpec import CHOICE_ANSWER_TYPES

if TYPE_CHECKING:
    from omr_data_collector.models.AnswerSpec import AnswerSpec
    from omr_data_collector.models.TableBlock import Column, TableBlock

# OMR marks need room: a bubble about 4.5 mm across fits a pen stroke, and 7 mm
# between bubble centres keeps a sloppy mark from touching its neighbour.
BUBBLE_DIAMETER_MM = 4.5
BUBBLE_PITCH_MM = 7.0
# One handwritten character per box.
WRITTEN_BOX_WIDTH_MM = 5.0
ROW_HEIGHT_MM = 8.0
CELL_PADDING_MM = 1.5
HEADER_POINT_SIZE = 8
CHOICE_LABEL_POINT_SIZE = 7
LABEL_GAP_MM = 1.0


@dataclass(frozen=True)
class ColumnLayout:
    width_mm: float
    # Distance between bubble centres; 0 for a written column.
    choice_pitch_mm: float


@dataclass(frozen=True)
class TableLayout:
    columns: tuple[ColumnLayout, ...]
    header_height_mm: float
    row_height_mm: float
    rows: int

    @property
    def width_mm(self) -> float:
        return sum(column.width_mm for column in self.columns)

    @property
    def height_mm(self) -> float:
        return self.header_height_mm + self.rows * self.row_height_mm

    def rows_per_page(self, printable_height_mm: float) -> int:
        """How many rows fit below the header on one page."""
        room = printable_height_mm - self.header_height_mm
        return max(int(room // self.row_height_mm), 0)


def choice_pitch_mm(answer: AnswerSpec) -> float:
    """Bubble spacing: the standard pitch, or wider if a choice's label needs it."""
    if answer.answer_type not in CHOICE_ANSWER_TYPES:
        return 0
    widest_label = max(
        (
            text_width_mm(choice.label, CHOICE_LABEL_POINT_SIZE)
            for choice in answer.printed_choices()
        ),
        default=0,
    )
    return max(BUBBLE_PITCH_MM, widest_label + LABEL_GAP_MM)


def column_layout(column: Column) -> ColumnLayout:
    answer = column.answer
    pitch = choice_pitch_mm(answer)
    if answer.answer_type == ANSWER_TYPES.WRITTEN:
        content = answer.characters() * WRITTEN_BOX_WIDTH_MM
    else:
        content = len(answer.printed_choices()) * pitch
    # The heading never wraps, so a column is at least as wide as its name; a
    # longer example wraps under it instead.
    heading = text_width_mm(column.name, HEADER_POINT_SIZE, bold=True)
    return ColumnLayout(
        width_mm=max(content, heading) + 2 * CELL_PADDING_MM, choice_pitch_mm=pitch
    )


def rows_to_print(table: TableBlock, space_mm: float) -> int:
    """How many rows the table prints when ``space_mm`` of page height is left.

    A fixed count, or for a table that fills to the end of its page, every row
    that fits below its header.
    """
    if not table.fill_page:
        return table.rows
    return table_layout(table).rows_per_page(space_mm)


def table_layout(table: TableBlock) -> TableLayout:
    has_example = any(column.example for column in table.columns)
    has_choices = any(
        column.answer.answer_type in CHOICE_ANSWER_TYPES for column in table.columns
    )
    header = 2 * CELL_PADDING_MM + line_height_mm(HEADER_POINT_SIZE)
    if has_example:
        header += line_height_mm(HEADER_POINT_SIZE)
    if has_choices:
        # Choice labels sit in a line of their own, above their bubbles.
        header += line_height_mm(CHOICE_LABEL_POINT_SIZE) + LABEL_GAP_MM
    return TableLayout(
        columns=tuple(column_layout(column) for column in table.columns),
        header_height_mm=header,
        row_height_mm=ROW_HEIGHT_MM,
        rows=table.rows,
    )


# Written boxes in a table row; shorter than a question's so rows stay compact.
TABLE_BOX_HEIGHT_MM = 6.0


def cell_bubble_centres_mm(column: Column, layout: ColumnLayout) -> list[float]:
    """Each choice bubble's centre across its cell, from the column's left edge."""
    count = len(column.answer.printed_choices())
    if column.answer.answer_type == ANSWER_TYPES.WRITTEN or not count:
        return []
    pitch = (layout.width_mm - 2 * CELL_PADDING_MM) / count
    return [CELL_PADDING_MM + (index + 0.5) * pitch for index in range(count)]


def cell_written_marks_mm(
    column: Column, layout: ColumnLayout
) -> list[tuple[float, str]]:
    """The boxes and printed separators in a written cell, centred in it.

    Each is its left edge from the column's left, and what goes there: ``""``
    for a box, or the character printed (see ``AnswerSpec.written_cells``). A
    free-text cell has none: the cell is the space to write in.
    """
    cells = column.answer.written_cells()
    if not cells:
        return []
    inner = layout.width_mm - 2 * CELL_PADDING_MM
    left = CELL_PADDING_MM + (inner - len(cells) * WRITTEN_BOX_WIDTH_MM) / 2
    return [
        (left + index * WRITTEN_BOX_WIDTH_MM, cell) for index, cell in enumerate(cells)
    ]
