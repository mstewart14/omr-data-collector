"""Sizes of a table block on paper, in millimetres.

The preview uses this now; printing and the OMRChecker template will use the same
numbers, so what is previewed is what is printed and scanned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from omr_data_collector.constants import ANSWER_TYPES
from omr_data_collector.layout.text import (  # noqa: F401 (MM_PER_POINT re-exported)
    MM_PER_POINT,
    line_height_mm,
    text_width_mm,
)
from omr_data_collector.models.AnswerSpec import CHOICE_ANSWER_TYPES
from omr_data_collector.models.FormFont import STANDARD_FONT, FormFont

if TYPE_CHECKING:
    from omr_data_collector.models.AnswerSpec import AnswerSpec
    from omr_data_collector.models.TableBlock import Column, TableBlock

# A bubble 3 mm across, the size Gambit's pick'em sheets print theirs, is quick
# to fill with a pen or pencil; 7 mm between bubble centres keeps a sloppy mark
# from touching its neighbour.
BUBBLE_DIAMETER_MM = 3.0
BUBBLE_PITCH_MM = 7.0
# One handwritten character per box.
WRITTEN_BOX_WIDTH_MM = 5.0
ROW_HEIGHT_MM = 8.0
CELL_PADDING_MM = 1.5
HEADER_POINT_SIZE = 8
CHOICE_LABEL_POINT_SIZE = 7
LABEL_GAP_MM = 1.0
# A heading wider than its answer wraps at spaces onto at most this many lines.
MAX_HEADING_LINES = 3
# Finding the narrowest width that fits the heading in those lines: close enough.
HEADING_FIT_MM = 0.1


@dataclass(frozen=True)
class ColumnLayout:
    width_mm: float
    # Distance between bubble centres; 0 for a written column.
    choice_pitch_mm: float
    # The heading as printed, a line each. Layouts stored before headings
    # wrapped have none, and print the name on one line.
    heading_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableLayout:
    columns: tuple[ColumnLayout, ...]
    header_height_mm: float
    row_height_mm: float
    rows: int
    # What its text was measured in, and so must be drawn in.
    font: FormFont = field(default_factory=FormFont)

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


def choice_pitch_mm(answer: AnswerSpec, *, font: FormFont) -> float:
    """Bubble spacing: the standard pitch, or wider if a choice's label needs it."""
    if answer.answer_type not in CHOICE_ANSWER_TYPES:
        return 0
    widest_label = max(
        (
            text_width_mm(choice.label, CHOICE_LABEL_POINT_SIZE, font=font)
            for choice in answer.printed_choices()
        ),
        default=0,
    )
    return max(BUBBLE_PITCH_MM, widest_label + LABEL_GAP_MM)


def column_layout(column: Column, *, font: FormFont = STANDARD_FONT) -> ColumnLayout:
    answer = column.answer
    pitch = choice_pitch_mm(answer, font=font)
    if answer.answer_type == ANSWER_TYPES.WRITTEN:
        content = answer.characters() * WRITTEN_BOX_WIDTH_MM
    else:
        content = len(answer.printed_choices()) * pitch
    heading = _heading_width(column.name, font)
    lines = (column.name,)
    if column.wrap_heading and heading > content:
        # Only as wide as the answer needs, the heading taking more lines.
        lines = _wrapped_heading(column.name, content, font)
        heading = max(_heading_width(line, font) for line in lines)
    return ColumnLayout(
        width_mm=max(content, heading) + 2 * CELL_PADDING_MM,
        choice_pitch_mm=pitch,
        heading_lines=lines,
    )


def _heading_width(text: str, font: FormFont) -> float:
    return text_width_mm(text, HEADER_POINT_SIZE, font=font, bold=True)


def _wrapped_heading(name: str, content_mm: float, font: FormFont) -> tuple[str, ...]:
    """``name`` in at most MAX_HEADING_LINES lines, as narrow as it can be.

    Never narrower than its answer (``content_mm``) or its longest word: a word
    is never split.
    """
    words = name.split()
    if len(words) < 2:
        return (name,)

    def wrap(width: float) -> list[str]:
        lines = [words[0]]
        for word in words[1:]:
            joined = f"{lines[-1]} {word}"
            if _heading_width(joined, font) <= width:
                lines[-1] = joined
            else:
                lines.append(word)
        return lines

    narrowest = max(content_mm, *(_heading_width(word, font) for word in words))
    widest = _heading_width(" ".join(words), font)
    if len(wrap(narrowest)) > MAX_HEADING_LINES:
        # The narrowest width that keeps it to the lines allowed.
        while widest - narrowest > HEADING_FIT_MM:
            middle = (narrowest + widest) / 2
            if len(wrap(middle)) > MAX_HEADING_LINES:
                narrowest = middle
            else:
                widest = middle
        narrowest = widest
    return tuple(wrap(narrowest))


def rows_to_print(
    table: TableBlock, space_mm: float, *, font: FormFont = STANDARD_FONT
) -> int:
    """How many rows the table prints when ``space_mm`` of page height is left.

    A fixed count, or for a table that fills to the end of its page, every row
    that fits below its header.
    """
    if not table.fill_page:
        return table.rows
    return table_layout(table, font=font).rows_per_page(space_mm)


def table_layout(table: TableBlock, *, font: FormFont = STANDARD_FONT) -> TableLayout:
    """The table's sizes in ``font`` (the standard one outside a form)."""
    has_example = any(column.example for column in table.columns)
    has_choices = any(
        column.answer.answer_type in CHOICE_ANSWER_TYPES for column in table.columns
    )
    columns = tuple(column_layout(column, font=font) for column in table.columns)
    line = line_height_mm(HEADER_POINT_SIZE, font=font)
    header = 2 * CELL_PADDING_MM + heading_line_count(columns) * line
    if has_example:
        header += line
    if has_choices:
        # Choice labels sit in a line of their own, above their bubbles.
        header += line_height_mm(CHOICE_LABEL_POINT_SIZE, font=font) + LABEL_GAP_MM
    return TableLayout(
        columns=columns,
        header_height_mm=header,
        row_height_mm=ROW_HEIGHT_MM,
        rows=table.rows,
        font=font,
    )


# Written boxes in a table row; shorter than a question's so rows stay compact.
TABLE_BOX_HEIGHT_MM = 6.0


def heading_line_count(columns: tuple[ColumnLayout, ...]) -> int:
    """The lines the headings take: the most any column's heading needs."""
    return max((len(column.heading_lines) for column in columns), default=1) or 1


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
