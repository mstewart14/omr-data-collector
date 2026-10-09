"""The OMRChecker template for one printed page, generated from its layout.

The template's coordinates are pixels measured from the top-left marker's centre:
OMRChecker first finds the page (CropPage), then straightens it on the four
corner markers (CropOnMarkers), so the marker centres become the template's
corners. Everything else is placed from the same layout the page was drawn from.

Each bubble's value in the template is a letter, A for a field's first choice, B
for its second and so on (questions have at most 20 choices). OMRChecker joins
the letters of every bubble marked in a field, so "AC" always means the first and
third choices, whatever their saved values; ``TemplateField`` maps them back.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from omr_data_collector.layout.markers import MARKER_DIAMETER_MM, marker_centres_mm
from omr_data_collector.layout.table_layout import (
    BUBBLE_DIAMETER_MM,
    cell_bubble_centres_mm,
)
from omr_data_collector.models.AnswerSpec import CHOICE_ANSWER_TYPES
from omr_data_collector.models.Question import Question
from omr_data_collector.models.SheetDetails import SheetDetails
from omr_data_collector.models.TableBlock import TableBlock

if TYPE_CHECKING:
    from omr_data_collector.layout.form_layout import (
        FormLayout,
        PageLayout,
        PlacedBlock,
    )

# How finely the template measures the straightened page.
TEMPLATE_PX_PER_MM = 6.0
# The working size OMRChecker shrinks a photo to while finding the page and the
# markers: plenty for 6 mm discs, and quick.
PROCESSING_PX_PER_MM = 4.0
MARKER_FILE_NAME = "marker.png"
MARKER_IMAGE_PX = 120
CHOICE_LETTERS = string.ascii_uppercase


@dataclass(frozen=True)
class TemplateField:
    """What one template field reads: a question's row of choices, or a table cell.

    ``first_choice`` is the choice index of the field's letter A; the letter in
    position n of OMRChecker's value is choice ``first_choice + n``.
    """

    block_index: int
    first_choice: int
    choice_count: int
    table_row: int | None = None
    column: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "blockIndex": self.block_index,
            "firstChoice": self.first_choice,
            "choiceCount": self.choice_count,
            "tableRow": self.table_row,
            "column": self.column,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemplateField:
        return cls(
            block_index=data["blockIndex"],
            first_choice=data["firstChoice"],
            choice_count=data["choiceCount"],
            table_row=data["tableRow"],
            column=data["column"],
        )

    def choices_marked(self, value: str) -> list[int]:
        """The choice indices for the letters OMRChecker read in this field."""
        return [
            CHOICE_LETTERS.index(letter)
            for letter in value
            if letter
            in CHOICE_LETTERS[self.first_choice : self.first_choice + self.choice_count]
        ]


@dataclass(frozen=True)
class AnswerRegion:
    """Where one answer is on the straightened page, bubbles or handwriting.

    A question's region is its whole block (prompt and answer), a table answer's
    is its cell. ``rect`` is x, y, width and height in template pixels, the same
    as the straightened page image OMRChecker saves, so the region can be cut out
    of it for a close-up.
    """

    block_index: int
    rect: tuple[int, int, int, int]
    table_row: int | None = None
    column: int | None = None

    @property
    def key(self) -> tuple[int, int | None, int | None]:
        return self.block_index, self.table_row, self.column

    def to_dict(self) -> dict[str, Any]:
        return {
            "blockIndex": self.block_index,
            "rect": list(self.rect),
            "tableRow": self.table_row,
            "column": self.column,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnswerRegion:
        x, y, width, height = data["rect"]
        return cls(
            block_index=data["blockIndex"],
            rect=(x, y, width, height),
            table_row=data["tableRow"],
            column=data["column"],
        )


@dataclass(frozen=True)
class PageTemplate:
    """A page's template.json content, and what each of its fields means.

    ``regions`` says where every answer on the page is, in reading order,
    written answers included.
    """

    template: dict[str, Any]
    fields: dict[str, TemplateField]
    regions: tuple[AnswerRegion, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "template": self.template,
            "fields": {label: field.to_dict() for label, field in self.fields.items()},
            "regions": [region.to_dict() for region in self.regions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PageTemplate:
        return cls(
            template=data["template"],
            fields={
                label: TemplateField.from_dict(field)
                for label, field in data["fields"].items()
            },
            regions=tuple(
                AnswerRegion.from_dict(region) for region in data.get("regions", [])
            ),
        )


def printed_layout(layout: FormLayout) -> dict[str, Any]:
    """Every page's template, to store when a version is printed."""
    return {"pages": [page_template(layout, page).to_dict() for page in layout.pages]}


def page_template(layout: FormLayout, page: PageLayout) -> PageTemplate:
    """The OMRChecker template for one page of a laid-out form."""
    (left, top), _, (right, bottom), _ = marker_centres_mm(
        layout.paper_width_mm, layout.paper_height_mm
    )

    def px(value_mm: float, origin_mm: float) -> int:
        return round((value_mm - origin_mm) * TEMPLATE_PX_PER_MM)

    bubble = round(BUBBLE_DIAMETER_MM * TEMPLATE_PX_PER_MM)
    blocks: dict[str, dict[str, Any]] = {}
    fields: dict[str, TemplateField] = {}
    bubble_types: dict[str, dict[str, Any]] = {}

    def add_block(  # noqa: PLR0913 (a field block's whole description)
        name: str,
        centre_x_mm: float,
        centre_y_mm: float,
        letters: str,
        pitch_mm: float,
        labels: list[str],
        row_pitch_mm: float = 0,
    ) -> None:
        type_name = f"CUSTOM_{letters}"
        bubble_types[type_name] = {
            "bubbleValues": list(letters),
            "direction": "horizontal",
        }
        blocks[name] = {
            "fieldDetectionType": "BUBBLES_THRESHOLD",
            "bubbleFieldType": type_name,
            # The block's origin is its first bubble's top-left corner.
            "origin": [
                px(centre_x_mm - BUBBLE_DIAMETER_MM / 2, left),
                px(centre_y_mm - BUBBLE_DIAMETER_MM / 2, top),
            ],
            "bubblesGap": round(pitch_mm * TEMPLATE_PX_PER_MM, 2),
            "labelsGap": round(row_pitch_mm * TEMPLATE_PX_PER_MM, 2),
            "fieldLabels": labels,
        }

    def rect(
        x_mm: float, y_mm: float, width_mm: float, height_mm: float
    ) -> tuple[int, int, int, int]:
        x, y = px(x_mm, left), px(y_mm, top)
        return x, y, px(x_mm + width_mm, left) - x, px(y_mm + height_mm, top) - y

    regions: list[AnswerRegion] = []
    for placed in page.blocks:
        content = placed.block.content
        if isinstance(content, Question) and placed.question is not None:
            _add_question(placed, content, add_block, fields)
            regions.append(
                AnswerRegion(
                    placed.index,
                    rect(0, placed.y_mm, layout.width_mm, placed.height_mm),
                )
            )
        elif isinstance(content, TableBlock) and placed.table_part is not None:
            _add_table_part(placed, content, add_block, fields)
            regions += _table_regions(placed, rect)
        elif isinstance(content, SheetDetails) and placed.details is not None:
            regions += _add_details(placed, add_block, fields, rect)

    template = {
        "templateDimensions": [px(right, left), px(bottom, top)],
        "bubbleDimensions": [bubble, bubble],
        "emptyValue": "",
        "preProcessors": _pre_processors(layout),
        "customBubbleFieldTypes": bubble_types,
        "fieldBlocks": blocks,
    }
    return PageTemplate(template=template, fields=fields, regions=tuple(regions))


def marker_image() -> np.ndarray:
    """The marker as OMRChecker matches it: a black disc filling a white square."""
    size = MARKER_IMAGE_PX
    y, x = np.ogrid[:size, :size]
    centre = (size - 1) / 2
    disc = (x - centre) ** 2 + (y - centre) ** 2 <= (size / 2) ** 2
    return np.where(disc, 0, 255).astype(np.uint8)


def _pre_processors(layout: FormLayout) -> list[dict[str, Any]]:
    processing_shape = [
        round(layout.paper_height_mm * PROCESSING_PX_PER_MM),
        round(layout.paper_width_mm * PROCESSING_PX_PER_MM),
    ]
    marker = round(MARKER_DIAMETER_MM * PROCESSING_PX_PER_MM)
    return [
        # Find the sheet against whatever it was photographed on.
        {
            "name": "CropPage",
            "options": {
                "morphKernel": [10, 10],
                "processingImageShape": processing_shape,
            },
        },
        # Straighten it on the four corner markers' centres.
        {
            "name": "CropOnMarkers",
            "options": {
                "type": "FOUR_MARKERS",
                "referenceImage": MARKER_FILE_NAME,
                "markerDimensions": [marker, marker],
                "processingImageShape": processing_shape,
                "defaultSelector": "CENTERS",
            },
        },
    ]


def _add_question(placed: PlacedBlock, question: Question, add_block, fields) -> None:
    geometry = placed.question
    if geometry is None or question.answer.answer_type not in CHOICE_ANSWER_TYPES:
        return
    rows: dict[int, list] = {}
    for bubble in geometry.bubbles:
        rows.setdefault(bubble.row, []).append(bubble)
    for row, bubbles in rows.items():
        label = f"q{placed.index}r{row}"
        first = bubbles[0].choice_index
        add_block(
            label,
            bubbles[0].centre_x_mm,
            placed.y_mm + bubbles[0].centre_y_mm,
            CHOICE_LETTERS[first : first + len(bubbles)],
            geometry.choice_pitch_mm,
            [label],
        )
        fields[label] = TemplateField(placed.index, first, len(bubbles))


def _add_details(placed: PlacedBlock, add_block, fields, rect) -> list[AnswerRegion]:
    """A field block for each field answered with bubbles; a region for every field."""
    geometry = placed.details
    if geometry is None:
        return []
    regions = []
    for detail in geometry.fields:
        if detail.bubbles:
            label = f"d{placed.index}f{detail.field_index}"
            first = detail.bubbles[0]
            add_block(
                label,
                first.centre_x_mm,
                placed.y_mm + first.centre_y_mm,
                CHOICE_LETTERS[: len(detail.bubbles)],
                detail.choice_pitch_mm,
                [label],
            )
            fields[label] = TemplateField(
                placed.index, 0, len(detail.bubbles), column=detail.field_index
            )
        regions.append(
            AnswerRegion(
                placed.index,
                rect(
                    detail.x_mm,
                    placed.y_mm + detail.y_mm,
                    detail.width_mm,
                    geometry.row_height_mm,
                ),
                column=detail.field_index,
            )
        )
    return regions


def _table_regions(placed: PlacedBlock, rect) -> list[AnswerRegion]:
    """Each cell of a table part, row by row."""
    part = placed.table_part
    if part is None:
        return []
    layout = part.layout
    top = placed.y_mm + part.grid_top_mm + layout.header_height_mm
    regions = []
    for offset in range(part.row_count):
        x = 0.0
        for column, column_layout in enumerate(layout.columns):
            regions.append(
                AnswerRegion(
                    placed.index,
                    rect(
                        x,
                        top + offset * layout.row_height_mm,
                        column_layout.width_mm,
                        layout.row_height_mm,
                    ),
                    table_row=part.first_row + offset,
                    column=column,
                )
            )
            x += column_layout.width_mm
    return regions


def _add_table_part(placed: PlacedBlock, table: TableBlock, add_block, fields) -> None:
    part = placed.table_part
    if part is None:
        return
    layout = part.layout
    x = 0.0
    for column_index, (column, column_layout) in enumerate(
        zip(table.columns, layout.columns, strict=True)
    ):
        centres = cell_bubble_centres_mm(column, column_layout)
        if centres:
            rows = range(part.first_row, part.first_row + part.row_count)
            labels = [f"t{placed.index}c{column_index}r{row}" for row in rows]
            pitch = centres[1] - centres[0] if len(centres) > 1 else 0
            add_block(
                f"t{placed.index}c{column_index}p{part.first_row}",
                x + centres[0],
                placed.y_mm
                + part.grid_top_mm
                + layout.header_height_mm
                + layout.row_height_mm / 2,
                CHOICE_LETTERS[: len(centres)],
                pitch,
                labels,
                row_pitch_mm=layout.row_height_mm,
            )
            for row, label in zip(rows, labels, strict=True):
                fields[label] = TemplateField(
                    placed.index, 0, len(centres), table_row=row, column=column_index
                )
        x += column_layout.width_mm
