"""Where everything on a form's pages goes, in millimetres (wiki 50005, 50006).

Blocks stack down each page, full width, under a header that has the
organization's identity on the left and the form's QR code in the top-right
corner. The editor, printing and the OMRChecker template all read this one
layout, so what is seen is what is printed is what is scanned.

Coordinates are relative to the top-left of the printable area (inside the page
margins), x to the right and y down.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from PySide6.QtGui import QPageLayout

from omr_data_collector.constants import ANSWER_TYPES, TABLE_BREAKS
from omr_data_collector.i18n import tr
from omr_data_collector.layout.page_setup import (
    page_layout_for,
    printable_size_mm,
)
from omr_data_collector.layout.table_layout import (
    BUBBLE_DIAMETER_MM,
    WRITTEN_BOX_WIDTH_MM,
    TableLayout,
    table_layout,
)
from omr_data_collector.layout.text import (
    document_height_mm,
    markdown_document,
    plain_document,
    text_width_mm,
)
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TableBlock import TableBlock
from omr_data_collector.models.TextBlock import TextBlock

if TYPE_CHECKING:
    from omr_data_collector.models.Form import Form, FormBlock

HEADER_HEIGHT_MM = 24.0
# The QR code, quiet zone included, sits in the header's top-right corner.
QR_SIZE_MM = 22.0
HEADER_GAP_MM = 4.0
CONTENT_TOP_MM = HEADER_HEIGHT_MM + HEADER_GAP_MM
BLOCK_GAP_MM = 5.0

BODY_POINT_SIZE = 10
EXAMPLE_POINT_SIZE = 8.5
ANSWER_LABEL_POINT_SIZE = 9
PART_GAP_MM = 1.5
ANSWER_ROW_HEIGHT_MM = 8.0
WRITTEN_BOX_HEIGHT_MM = 7.0
BUBBLE_LABEL_GAP_MM = 1.5
CHOICE_SPACING_MM = 5.0
INSTRUCTIONS_GAP_MM = 2.0
# Free text is written on a line this far down its row: room above for the
# letters, as on lined paper.
WRITING_LINE_DROP_MM = 7.0


@dataclass(frozen=True)
class Bubble:
    """One answer bubble, its centre relative to the block's top-left."""

    centre_x_mm: float
    centre_y_mm: float
    label: str
    choice_index: int
    # Which row of the question's choices it is on (they wrap when many).
    row: int = 0


@dataclass(frozen=True)
class WrittenBox:
    """One character position of a boxed answer, relative to the block's top-left.

    ``printed`` is empty for a box to write in, or the character printed there
    already: the ``/`` or ``:`` of a date or time (a space prints nothing).
    """

    x_mm: float
    y_mm: float
    width_mm: float = WRITTEN_BOX_WIDTH_MM
    height_mm: float = WRITTEN_BOX_HEIGHT_MM
    printed: str = ""


@dataclass(frozen=True)
class WritingLine:
    """A line to write free text on, relative to the block's top-left."""

    x_mm: float
    y_mm: float
    width_mm: float


@dataclass(frozen=True)
class QuestionGeometry:
    prompt_height_mm: float
    example_top_mm: float
    example_height_mm: float
    answer_top_mm: float
    # Distance between neighbouring bubbles' centres in a row of choices.
    choice_pitch_mm: float
    bubbles: tuple[Bubble, ...]
    boxes: tuple[WrittenBox, ...]
    lines: tuple[WritingLine, ...]
    height_mm: float


@dataclass(frozen=True)
class TablePart:
    """The rows of a table that land on one page, with or without its instructions."""

    first_row: int
    layout: TableLayout
    instructions_height_mm: float
    # Where the table's grid starts, below any instructions, relative to the block.
    grid_top_mm: float

    @property
    def row_count(self) -> int:
        return self.layout.rows

    @property
    def continued(self) -> bool:
        return self.first_row > 0

    @property
    def height_mm(self) -> float:
        return self.grid_top_mm + self.layout.height_mm


@dataclass(frozen=True)
class PlacedBlock:
    """A block, or for a split table one part of it, placed on a page."""

    index: int
    block: FormBlock
    y_mm: float
    height_mm: float
    question: QuestionGeometry | None = None
    table_part: TablePart | None = None


@dataclass(frozen=True)
class PageLayout:
    number: int
    blocks: tuple[PlacedBlock, ...]


@dataclass(frozen=True)
class FormLayout:
    pages: tuple[PageLayout, ...]
    # The printable area, inside the margins, which the coordinates are within.
    width_mm: float
    height_mm: float
    warnings: tuple[str, ...]
    # The whole sheet, margins included: where the corner markers go.
    paper_width_mm: float = 0.0
    paper_height_mm: float = 0.0


def layout_form(form: Form, paper_size: str) -> FormLayout:
    """Stack the form's blocks down pages of ``paper_size`` in its orientation."""
    width, height = printable_size_mm(paper_size, form.orientation)
    paper = page_layout_for(paper_size, form.orientation).fullRect(
        QPageLayout.Unit.Millimeter
    )
    builder = _PageBuilder(width, height)
    for index, block in enumerate(form.blocks):
        builder.place(index, block)
    return FormLayout(
        pages=builder.finish(),
        width_mm=width,
        height_mm=height,
        warnings=tuple(builder.warnings),
        paper_width_mm=paper.width(),
        paper_height_mm=paper.height(),
    )


def question_geometry(question: Question, width_mm: float) -> QuestionGeometry:
    """Where a question's parts go, ``width_mm`` wide."""
    prompt = document_height_mm(
        markdown_document(question.prompt, width_mm, BODY_POINT_SIZE)
    )
    y = prompt
    example_top = y
    example = 0.0
    if question.example:
        example_top = y + PART_GAP_MM
        example = document_height_mm(
            plain_document(question.example, width_mm, EXAMPLE_POINT_SIZE, italic=True)
        )
        y = example_top + example
    answer_top = y + PART_GAP_MM
    if question.answer.answer_type == ANSWER_TYPES.WRITTEN:
        cells = question.answer.written_cells()
        if cells is None:
            lines = _writing_lines(question.answer.characters(), width_mm, answer_top)
            bottom = lines[-1].y_mm + (ANSWER_ROW_HEIGHT_MM - WRITING_LINE_DROP_MM)
            return QuestionGeometry(
                prompt, example_top, example, answer_top, 0.0, (), (), lines, bottom
            )
        boxes = _written_boxes(cells, width_mm, answer_top)
        bottom = max(box.y_mm + box.height_mm for box in boxes)
        return QuestionGeometry(
            prompt, example_top, example, answer_top, 0.0, (), boxes, (), bottom
        )
    pitch = _choice_pitch_mm(question)
    bubbles = _choice_bubbles(question, width_mm, answer_top, pitch)
    bottom = max(bubble.centre_y_mm for bubble in bubbles) + ANSWER_ROW_HEIGHT_MM / 2
    return QuestionGeometry(
        prompt, example_top, example, answer_top, pitch, bubbles, (), (), bottom
    )


def _choice_pitch_mm(question: Question) -> float:
    """The spacing of a question's bubbles: room for the widest label.

    Evenly spaced bubbles line up neatly, and OMRChecker reads a row of them as
    one field only when they are evenly spaced.
    """
    widest = max(
        (
            text_width_mm(choice.label, ANSWER_LABEL_POINT_SIZE)
            for choice in question.answer.printed_choices()
        ),
        default=0.0,
    )
    return BUBBLE_DIAMETER_MM + BUBBLE_LABEL_GAP_MM + widest + CHOICE_SPACING_MM


def _choice_bubbles(
    question: Question, width_mm: float, top: float, pitch: float
) -> tuple[Bubble, ...]:
    """Bubbles left to right, each followed by its label, wrapping onto new rows."""
    item = pitch - CHOICE_SPACING_MM
    per_row = max(int((width_mm - item) // pitch) + 1, 1)
    return tuple(
        Bubble(
            centre_x_mm=(index % per_row) * pitch + BUBBLE_DIAMETER_MM / 2,
            centre_y_mm=top
            + (index // per_row) * ANSWER_ROW_HEIGHT_MM
            + ANSWER_ROW_HEIGHT_MM / 2,
            label=choice.label,
            choice_index=index,
            row=index // per_row,
        )
        for index, choice in enumerate(question.answer.printed_choices())
    )


def _written_boxes(
    cells: tuple[str, ...], width_mm: float, top: float
) -> tuple[WrittenBox, ...]:
    """One position per character, wrapping onto new rows when the page is narrow."""
    per_row = max(int(width_mm // WRITTEN_BOX_WIDTH_MM), 1)
    margin = (ANSWER_ROW_HEIGHT_MM - WRITTEN_BOX_HEIGHT_MM) / 2
    return tuple(
        WrittenBox(
            x_mm=(index % per_row) * WRITTEN_BOX_WIDTH_MM,
            y_mm=top + (index // per_row) * ANSWER_ROW_HEIGHT_MM + margin,
            printed=printed,
        )
        for index, printed in enumerate(cells)
    )


def _writing_lines(
    characters: int, width_mm: float, top: float
) -> tuple[WritingLine, ...]:
    """Lines as long as ``characters`` boxes would be, wrapped to the page width."""
    remaining = max(characters, 1) * WRITTEN_BOX_WIDTH_MM
    lines = []
    row = 0
    while remaining > 0:
        length = min(remaining, width_mm)
        lines.append(
            WritingLine(
                x_mm=0,
                y_mm=top + row * ANSWER_ROW_HEIGHT_MM + WRITING_LINE_DROP_MM,
                width_mm=length,
            )
        )
        remaining -= length
        row += 1
    return tuple(lines)


class _PageBuilder:
    """Fills pages top to bottom, starting new ones as blocks require."""

    def __init__(self, width_mm: float, height_mm: float) -> None:
        self.width = width_mm
        self.height = height_mm
        self.pages: list[list[PlacedBlock]] = [[]]
        self.y = CONTENT_TOP_MM
        self.warnings: list[str] = []

    @property
    def page_is_empty(self) -> bool:
        return not self.pages[-1]

    @property
    def space(self) -> float:
        return self.height - self.y

    def new_page(self) -> None:
        self.pages.append([])
        self.y = CONTENT_TOP_MM

    def put(self, placed: PlacedBlock) -> None:
        self.pages[-1].append(placed)
        self.y += placed.height_mm + BLOCK_GAP_MM

    def place(self, index: int, block: FormBlock) -> None:
        if block.start_on_new_page and not self.page_is_empty:
            self.new_page()
        content = block.content
        if isinstance(content, TableBlock):
            self._place_table(index, block, content)
            return
        question = None
        if isinstance(content, Question):
            question = question_geometry(content, self.width)
            height = question.height_mm
        else:
            assert isinstance(content, TextBlock)  # noqa: S101 (the only kind left)
            height = document_height_mm(
                markdown_document(content.content, self.width, BODY_POINT_SIZE)
            )
        # Text and questions are never split: one that doesn't fit moves down.
        if height > self.space and not self.page_is_empty:
            self.new_page()
        if height > self.height - CONTENT_TOP_MM:
            self.warnings.append(
                tr('"{name}" is taller than a page and runs off the bottom.').format(
                    name=content.name
                )
            )
        self.put(PlacedBlock(index, block, self.y, height, question=question))

    def _place_table(self, index: int, block: FormBlock, table: TableBlock) -> None:
        full = table_layout(table)
        if full.width_mm > self.width:
            self.warnings.append(
                tr(
                    'The table "{name}" is {width} mm wide but the page has {room} mm.'
                ).format(
                    name=table.name, width=round(full.width_mm), room=round(self.width)
                )
            )
        instructions = 0.0
        if table.instructions.strip():
            instructions = document_height_mm(
                markdown_document(table.instructions, self.width, BODY_POINT_SIZE)
            )
        grid_top = instructions + (INSTRUCTIONS_GAP_MM if instructions else 0)

        def rows_fitting(top: float) -> int:
            room = self.space - top - full.header_height_mm
            return max(int(room // full.row_height_mm), 0)

        if table.fill_page:
            # As many rows as fit below where the table lands (wiki 30001).
            if rows_fitting(grid_top) < 1 and not self.page_is_empty:
                self.new_page()
            rows = max(rows_fitting(grid_top), 1)
            self._put_table_part(index, block, full, 0, rows, instructions, grid_top)
            return

        remaining = table.rows
        fresh_page_rows = int(
            (self.height - CONTENT_TOP_MM - grid_top - full.header_height_mm)
            // full.row_height_mm
        )
        if (
            block.table_break == TABLE_BREAKS.NEW_PAGE
            and remaining > rows_fitting(grid_top)
            and remaining <= fresh_page_rows
            and not self.page_is_empty
        ):
            # Moves down whole rather than splitting, as the person chose.
            self.new_page()
        first_row = 0
        top = grid_top
        part_instructions = instructions
        while remaining > 0:
            fitting = rows_fitting(top)
            if fitting < 1 and not self.page_is_empty:
                self.new_page()
                fitting = max(rows_fitting(top), 1)
            rows = min(remaining, max(fitting, 1))
            self._put_table_part(
                index, block, full, first_row, rows, part_instructions, top
            )
            first_row += rows
            remaining -= rows
            if remaining:
                # The rest continues on the next page under a repeated heading.
                self.new_page()
                top, part_instructions = 0.0, 0.0

    def _put_table_part(  # noqa: PLR0913 (one part's position and contents)
        self,
        index: int,
        block: FormBlock,
        full: TableLayout,
        first_row: int,
        rows: int,
        instructions: float,
        grid_top: float,
    ) -> None:
        part = TablePart(
            first_row=first_row,
            layout=replace(full, rows=rows),
            instructions_height_mm=instructions,
            grid_top_mm=grid_top,
        )
        self.put(PlacedBlock(index, block, self.y, part.height_mm, table_part=part))

    def finish(self) -> tuple[PageLayout, ...]:
        return tuple(
            PageLayout(number=number, blocks=tuple(blocks))
            for number, blocks in enumerate(self.pages, start=1)
        )
