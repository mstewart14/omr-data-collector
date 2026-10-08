"""Round trip: lay out a form, draw it filled in, photograph it badly, scan it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter

from omr_data_collector.constants import ANSWER_TYPES, PAPER_SIZES, WRITTEN_DATA_TYPES
from omr_data_collector.engine.scanning import (
    ScanError,
    read_sheet_identity,
    scan_sheet,
)
from omr_data_collector.layout.form_layout import layout_form
from omr_data_collector.layout.markers import marker_centres_mm
from omr_data_collector.layout.omr_template import (
    PageTemplate,
    page_template,
    printed_layout,
)
from omr_data_collector.layout.page_setup import PAGE_MARGIN_MM
from omr_data_collector.layout.table_layout import cell_bubble_centres_mm
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.Organization import Organization
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.rendering.page_painter import paint_page
from omr_data_collector.storage.form_store import (
    load_printed_layout,
    mark_printed,
    save_form,
)
from omr_data_collector.storage.organization_store import save_organization

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from omr_data_collector.layout.form_layout import (
        FormLayout,
        PageLayout,
        PlacedBlock,
    )

pytestmark = pytest.mark.usefixtures("qapp")

LETTER = PAPER_SIZES.LETTER
PIXELS_PER_MM = 8
# Grey "table" showing around the sheet, as in a photo.
BORDER_MM = 20
FILL_RADIUS_MM = 1.9


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
        self.image = QImage(
            round((layout.paper_width_mm + 2 * BORDER_MM) * PIXELS_PER_MM),
            round((layout.paper_height_mm + 2 * BORDER_MM) * PIXELS_PER_MM),
            QImage.Format.Format_RGB32,
        )
        self.image.fill(QColor("#707070"))
        self.painter = QPainter(self.image)
        self.painter.scale(PIXELS_PER_MM, PIXELS_PER_MM)
        self.painter.translate(BORDER_MM, BORDER_MM)
        self.painter.fillRect(
            0,
            0,
            round(layout.paper_width_mm),
            round(layout.paper_height_mm),
            QColor("white"),
        )
        self.painter.translate(PAGE_MARGIN_MM, PAGE_MARGIN_MM)
        paint_page(self.painter, form, organization, layout, self.page)
        self.painter.setBrush(QColor("black"))

    def _placed(self, index: int) -> PlacedBlock:
        return next(block for block in self.page.blocks if block.index == index)

    def fill_question(self, index: int, *choices: int) -> None:
        placed = self._placed(index)
        assert placed.question is not None
        for bubble in placed.question.bubbles:
            if bubble.choice_index in choices:
                self._fill(bubble.centre_x_mm, placed.y_mm + bubble.centre_y_mm)

    def fill_cell(self, index: int, row: int, column: int, choice: int) -> None:
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
        self._fill(x + centres[choice], y)

    def cover_marker(self, corner: int) -> None:
        x, y = marker_centres_mm(
            self.layout.paper_width_mm, self.layout.paper_height_mm
        )[corner]
        self.painter.fillRect(round(x - 5), round(y - 5), 10, 10, QColor("white"))

    def _fill(self, x: float, y: float) -> None:
        self.painter.drawEllipse(QPointF(x, y), FILL_RADIUS_MM, FILL_RADIUS_MM)

    def photograph(self, path: Path, degrees: float = 2.0) -> Path:
        """Save as a slightly turned JPEG, as if taken by hand."""
        self.painter.end()
        png = path.with_suffix(".png")
        self.image.save(str(png))
        image = cv2.imread(str(png))
        assert image is not None
        height, width = image.shape[:2]
        turn = cv2.getRotationMatrix2D((width / 2, height / 2), degrees, 1.0)
        image = cv2.warpAffine(
            image, turn, (width, height), borderValue=(112, 112, 112)
        )
        cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return path


@pytest.fixture
def organization(connection: sqlite3.Connection) -> Organization:
    organization = Organization("Food Bank")
    save_organization(connection, organization)
    return organization


@pytest.fixture
def printed_form(
    connection: sqlite3.Connection, organization: Organization
) -> tuple[Form, FormLayout]:
    form = save_form(connection, intake_form())
    layout = layout_form(form, organization.paper_size)
    mark_printed(connection, form.form_id, form.version, printed_layout(layout))
    return form, layout


def answers_by_place(page) -> dict[tuple, tuple[str, ...]]:
    return {
        (answer.block_index, answer.table_row, answer.column): answer.values
        for answer in page.answers
    }


def test_a_filled_in_photo_reads_back_its_answers(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    form, layout = printed_form
    sheet = Sheet(form, organization, layout)
    # Question 0 (yes/no) is left empty.
    sheet.fill_question(1, 0, 3)
    sheet.fill_cell(2, row=0, column=1, choice=0)
    sheet.fill_cell(2, row=0, column=2, choice=2)
    sheet.fill_cell(2, row=2, column=2, choice=0)
    photo = sheet.photograph(tmp_path / "photo.jpg")

    page = scan_sheet(connection, photo, LETTER)

    assert page.identity.form_id == form.form_id
    assert page.identity.form_version == form.version
    assert page.identity.page == 1
    answers = answers_by_place(page)
    assert answers[0, None, None] == ("no",)
    assert answers[1, None, None] == ("food", "other")
    assert answers[2, 0, 1] == ("y",)
    assert answers[2, 0, 2] == ("referral",)
    assert answers[2, 2, 1] == ("n",)
    assert answers[2, 2, 2] == ("food",)
    assert answers[2, 1, 2] == ()
    assert all(not answer.problem for answer in page.answers)


def test_two_marks_where_one_is_allowed_are_flagged(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    form, layout = printed_form
    sheet = Sheet(form, organization, layout)
    sheet.fill_question(0, 0)
    sheet.fill_cell(2, row=1, column=2, choice=0)
    sheet.fill_cell(2, row=1, column=2, choice=1)
    photo = sheet.photograph(tmp_path / "photo.jpg")

    page = scan_sheet(connection, photo, LETTER)

    answers = {(a.block_index, a.table_row, a.column): a for a in page.answers}
    assert answers[0, None, None].values == ("yes",)
    assert not answers[0, None, None].problem
    service = answers[2, 1, 2]
    assert service.values == ("food", "clothing")
    assert "More than one" in service.problem


def test_a_missing_corner_marker_is_reported(
    connection: sqlite3.Connection,
    organization: Organization,
    printed_form: tuple[Form, FormLayout],
    tmp_path: Path,
) -> None:
    form, layout = printed_form
    sheet = Sheet(form, organization, layout)
    sheet.cover_marker(3)
    photo = sheet.photograph(tmp_path / "photo.jpg")

    with pytest.raises(ScanError, match="corner markers"):
        scan_sheet(connection, photo, LETTER)


def test_a_picture_without_our_qr_code_is_reported() -> None:
    blank = np.full((400, 300), 255, dtype=np.uint8)

    with pytest.raises(ScanError, match="QR code"):
        read_sheet_identity(blank)


def test_a_sheet_from_an_unknown_form_is_reported(
    connection: sqlite3.Connection, organization: Organization, tmp_path: Path
) -> None:
    form = intake_form()  # never saved here
    sheet = Sheet(form, organization, layout_form(form, LETTER))
    photo = sheet.photograph(tmp_path / "photo.jpg")

    with pytest.raises(ScanError, match="isn't on this computer"):
        scan_sheet(connection, photo, LETTER)


def test_printing_stores_every_pages_template(
    connection: sqlite3.Connection, printed_form: tuple[Form, FormLayout]
) -> None:
    form, layout = printed_form

    stored = load_printed_layout(connection, form.form_id, form.version)

    assert stored is not None
    (page,) = stored["pages"]
    assert PageTemplate.from_dict(page) == page_template(layout, layout.pages[0])


def test_the_template_has_a_field_per_question_row_and_table_cell() -> None:
    form = intake_form()
    layout = layout_form(form, LETTER)

    template = page_template(layout, layout.pages[0])

    assert set(template.fields) == {
        "q0r0",
        "q1r0",
        *(f"t2c{column}r{row}" for column in (1, 2) for row in range(6)),
    }
    blocks = template.template["fieldBlocks"]
    assert blocks["q1r0"]["fieldLabels"] == ["q1r0"]
    assert blocks["t2c2p0"]["fieldLabels"] == [f"t2c2r{row}" for row in range(6)]
    # The straightened page runs from the top-left marker's centre to the
    # bottom-right one's.
    (left, top), _, (right, bottom), _ = marker_centres_mm(
        layout.paper_width_mm, layout.paper_height_mm
    )
    assert template.template["templateDimensions"] == [
        round((right - left) * 6),
        round((bottom - top) * 6),
    ]
