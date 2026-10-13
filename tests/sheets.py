"""Filled-in sheets drawn as a photo would see them, for tests that read them."""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np
from PySide6.QtGui import QColor

from omr_data_collector.constants import ANSWER_TYPES, PAPER_SIZES, WRITTEN_DATA_TYPES
from omr_data_collector.layout.markers import marker_centres_mm
from omr_data_collector.layout.table_layout import cell_bubble_centres_mm
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.rendering.page_photo import (
    FILL_RADIUS_MM,
    begin_page_photo,
    fill_bubble,
)

if TYPE_CHECKING:
    from pathlib import Path

    from omr_data_collector.layout.form_layout import (
        FormLayout,
        PageLayout,
        PlacedBlock,
    )
    from omr_data_collector.models.Organization import Organization

LETTER = PAPER_SIZES.LETTER
PIXELS_PER_MM = 8
# Grey "table" showing around the sheet, as in a photo.
BORDER_MM = 20


def intake_form() -> Form:
    return Form(
        name="Intake",
        blocks=(
            FormBlock(
                Question(
                    "visit",
                    "First visit?",
                    answer=AnswerSpec(
                        ANSWER_TYPES.YES_NO,
                        choices=(Choice("Yes", "yes"), Choice("No", "no")),
                    ),
                )
            ),
            FormBlock(
                Question(
                    "services",
                    "Services?",
                    answer=AnswerSpec(
                        ANSWER_TYPES.MANY_CHOICES,
                        choices=tuple(
                            Choice(label, label.lower())
                            for label in ("Food", "Clothing", "Referral", "Other")
                        ),
                    ),
                )
            ),
            FormBlock(
                TableBlock(
                    "Log",
                    rows=6,
                    columns=(
                        Column(
                            "time",
                            answer=AnswerSpec(
                                ANSWER_TYPES.WRITTEN,
                                data_type=WRITTEN_DATA_TYPES.DATE_TIME,
                                date_time_format="HH:MM",
                            ),
                        ),
                        Column(
                            "first",
                            answer=AnswerSpec(
                                ANSWER_TYPES.YES_NO,
                                choices=(Choice("Y", "y"), Choice("N", "n")),
                            ),
                        ),
                        Column(
                            "service",
                            answer=AnswerSpec(
                                ANSWER_TYPES.ONE_CHOICE,
                                choices=(
                                    Choice("F", "food"),
                                    Choice("C", "clothing"),
                                    Choice("R", "referral"),
                                ),
                            ),
                        ),
                    ),
                )
            ),
        ),
    )


class Sheet:
    """A page drawn as a photo would see it, with bubbles to fill in."""

    def __init__(
        self, form: Form, organization: Organization, layout: FormLayout
    ) -> None:
        self.form = form
        self.layout = layout
        self.page: PageLayout = layout.pages[0]
        self.image, self.painter = begin_page_photo(
            form, organization, layout, self.page, PIXELS_PER_MM, BORDER_MM
        )

    def _placed(self, index: int) -> PlacedBlock:
        return next(block for block in self.page.blocks if block.index == index)

    def fill_question(self, index: int, *choices: int) -> None:
        placed = self._placed(index)
        assert placed.question is not None
        for bubble in placed.question.bubbles:
            if bubble.choice_index in choices:
                self._fill(bubble.centre_x_mm, placed.y_mm + bubble.centre_y_mm)

    def fill_detail(self, index: int, field: int, choice: int) -> None:
        placed = self._placed(index)
        assert placed.details is not None
        detail = next(f for f in placed.details.fields if f.field_index == field)
        bubble = detail.bubbles[choice]
        self._fill(bubble.centre_x_mm, placed.y_mm + bubble.centre_y_mm)

    def fill_cell(
        self,
        index: int,
        row: int,
        column: int,
        choice: int,
        radius_mm: float = FILL_RADIUS_MM,
    ) -> None:
        """Fill a table bubble; a smaller ``radius_mm`` fills only its middle."""
        placed = self._placed(index)
        part = placed.table_part
        assert part is not None
        table = self.form.blocks[index].content
        assert isinstance(table, TableBlock)
        columns = part.layout.columns
        x = sum(column_layout.width_mm for column_layout in columns[:column])
        centres = cell_bubble_centres_mm(table.columns[column], columns[column])
        y = (
            placed.y_mm
            + part.grid_top_mm
            + part.layout.header_height_mm
            + (row - part.first_row + 0.5) * part.layout.row_height_mm
        )
        self._fill(x + centres[choice], y, radius_mm)

    def cover_marker(self, corner: int) -> None:
        x, y = marker_centres_mm(
            self.layout.paper_width_mm, self.layout.paper_height_mm
        )[corner]
        self.painter.fillRect(round(x - 5), round(y - 5), 10, 10, QColor("white"))

    def use_mark(self, colour: QColor) -> None:
        """Fill the bubbles that follow in ``colour``: grey for light pencil."""
        self.painter.setBrush(colour)

    def _fill(self, x: float, y: float, radius_mm: float = FILL_RADIUS_MM) -> None:
        fill_bubble(self.painter, x, y, radius_mm)

    def photograph(
        self, path: Path, degrees: float = 2.0, *, dim_right: float = 0.0
    ) -> Path:
        """Save as a slightly turned JPEG, as if taken by hand.

        ``dim_right`` darkens the page from left to right, by up to that share
        at the right edge, as a lamp off to one side does.
        """
        self.painter.end()
        path.parent.mkdir(parents=True, exist_ok=True)
        png = path.with_suffix(".png")
        self.image.save(str(png))
        image = cv2.imread(str(png))
        assert image is not None
        height, width = image.shape[:2]
        turn = cv2.getRotationMatrix2D((width / 2, height / 2), degrees, 1.0)
        image = cv2.warpAffine(
            image, turn, (width, height), borderValue=(112, 112, 112)
        )
        if dim_right:
            light = np.linspace(1.0, 1.0 - dim_right, width)[np.newaxis, :, np.newaxis]
            image = (image * light).astype(np.uint8)
        cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return path
