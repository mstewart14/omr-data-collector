"""A check that an installed copy of the app can print and read a sheet.

``omr-data-collector --self-check [report]`` lays out a one-question form, draws
it filled in as a photo would show it, and scans it, in a throwaway folder. That
runs Qt's drawing, the QR code, OpenCV and OMRChecker from wherever the app was
installed, so the installer builds use it to fail on a missing library rather
than on someone's computer. It exits 0 when the answer reads back, 1 otherwise,
and writes what happened to ``report`` if given: a windowed app has no console.
"""

from __future__ import annotations

import tempfile
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from omr_data_collector.constants import ANSWER_TYPES, PAPER_SIZES
from omr_data_collector.engine.scanning import scan_sheet
from omr_data_collector.layout.form_layout import layout_form
from omr_data_collector.layout.omr_template import printed_layout
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Form import Form, FormBlock
from omr_data_collector.models.Organization import Organization
from omr_data_collector.models.Question import Question
from omr_data_collector.rendering.page_photo import begin_page_photo, fill_bubble
from omr_data_collector.storage.database import open_database
from omr_data_collector.storage.form_store import mark_printed, save_form
from omr_data_collector.storage.organization_store import save_organization

if TYPE_CHECKING:
    from omr_data_collector.layout.form_layout import FormLayout

PIXELS_PER_MM = 6
# Grey showing around the sheet, as in a photo.
BORDER_MM = 15
CHOICES = ("red", "green", "blue")
MARKED = 1


class SelfCheckError(Exception):
    """The sheet didn't read back as it was drawn."""


def _check_form() -> Form:
    return Form(
        name="Self check",
        blocks=(
            FormBlock(
                Question(
                    "colour",
                    "Colour?",
                    answer=AnswerSpec(
                        ANSWER_TYPES.ONE_CHOICE,
                        choices=tuple(Choice(c.title(), c) for c in CHOICES),
                    ),
                )
            ),
        ),
    )


def _draw_filled_in(
    form: Form, organization: Organization, layout: FormLayout, image_path: Path
) -> None:
    """Draw page 1 of ``form`` with one bubble filled in, as a photo would show it."""
    page = layout.pages[0]
    placed = page.blocks[0]
    if placed.question is None:
        msg = "the form's first block isn't a question"
        raise SelfCheckError(msg)
    bubble = placed.question.bubbles[MARKED]
    image, painter = begin_page_photo(
        form, organization, layout, page, PIXELS_PER_MM, BORDER_MM
    )
    try:
        fill_bubble(painter, bubble.centre_x_mm, placed.y_mm + bubble.centre_y_mm)
    finally:
        painter.end()
    if not image.save(str(image_path)):
        msg = f"couldn't save {image_path}"
        raise OSError(msg)


def check(folder: Path) -> str:
    """Print and read a sheet in ``folder``; returns what was read.

    Raises:
        SelfCheckError: The sheet read back wrong.
    """
    connection = open_database(folder / "check.sqlite3")
    try:
        organization = Organization("Self check", paper_size=PAPER_SIZES.LETTER)
        save_organization(connection, organization)
        form = save_form(connection, _check_form())
        layout = layout_form(form, organization.paper_size)
        mark_printed(connection, form.form_id, form.version, printed_layout(layout))
        photo = folder / "sheet.png"
        _draw_filled_in(form, organization, layout, photo)
        page = scan_sheet(connection, photo, organization.paper_size, folder / "work")
    finally:
        connection.close()
    values = page.answers[0].values
    if values != (CHOICES[MARKED],):
        msg = f"read {values!r} where {CHOICES[MARKED]!r} was marked"
        raise SelfCheckError(msg)
    return f"read {values!r} from form {page.identity.form_id}"


def run(report: Path | None) -> int:
    """Run the check, writing the outcome to ``report``; 0 when it passed."""
    try:
        with tempfile.TemporaryDirectory() as folder:
            outcome, status = "ok: " + check(Path(folder)), 0
    # Every failure is the report's to show.
    except Exception:
        outcome, status = "failed:\n" + traceback.format_exc(), 1
    if report is not None:
        report.write_text(outcome + "\n", encoding="utf-8")
    return status
