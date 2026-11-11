"""PDF scans: each page drawn as an image, added and read like a photo."""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np
import pytest

from omr_data_collector.constants import CAPTURE_STATUSES
from omr_data_collector.engine.reading import read_capture
from omr_data_collector.rendering.page_photo import save_as_pdf
from omr_data_collector.storage.capture_store import add_capture
from omr_data_collector.storage.pdf_pages import PAGE_DPI, PdfError, pdf_page_images
from tests.sheets import LETTER, Sheet

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from omr_data_collector.layout.form_layout import FormLayout
    from omr_data_collector.models.Form import Form
    from omr_data_collector.models.Organization import Organization

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture
def scan_pdf(
    organization: Organization, printed_form: tuple[Form, FormLayout], tmp_path: Path
) -> Path:
    """A scanning app's PDF of two filled-in intake sheets."""
    form, layout = printed_form
    first = Sheet(form, organization, layout)
    first.fill_question(1, 0, 3)
    second = Sheet(form, organization, layout)
    second.fill_cell(2, row=0, column=2, choice=1)
    return save_as_pdf(
        tmp_path / "upload" / "scan.pdf",
        first.photograph(tmp_path / "pictures" / "first.jpg"),
        second.photograph(tmp_path / "pictures" / "second.jpg"),
        dpi=PAGE_DPI,
    )


def test_each_page_becomes_an_image_at_scanning_resolution(
    scan_pdf: Path, tmp_path: Path
) -> None:
    pages = pdf_page_images(scan_pdf, tmp_path / "pages")

    assert [page.number for page in pages] == [1, 2]
    image = cv2.imread(str(pages[0].image))
    original = cv2.imread(str(tmp_path / "pictures" / "first.jpg"))
    assert image is not None
    assert original is not None
    # The pictures were put in the PDF at PAGE_DPI, so they come out their size.
    assert abs(image.shape[1] - original.shape[1]) <= 1
    assert abs(image.shape[0] - original.shape[0]) <= 1


def test_pages_are_drawn_on_white_paper(tmp_path: Path) -> None:
    # A PDF leaves the page transparent where nothing is drawn; read as an
    # image without its transparency, that would be black.
    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), np.zeros((100, 100, 4), dtype=np.uint8))
    pdf = save_as_pdf(tmp_path / "blank.pdf", blank, dpi=50)

    image = cv2.imread(str(pdf_page_images(pdf, tmp_path / "pages")[0].image))

    assert image is not None
    assert image.min() == 255


def test_a_file_that_isnt_a_pdf_is_refused(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_text("not a PDF")

    with pytest.raises(PdfError):
        pdf_page_images(broken, tmp_path / "pages")


def test_a_pdf_page_is_read_like_a_photo(
    connection: sqlite3.Connection,
    printed_form: tuple[Form, FormLayout],
    scan_pdf: Path,
    tmp_path: Path,
) -> None:
    form, _ = printed_form
    first, second = pdf_page_images(scan_pdf, tmp_path / "pages")

    one = read_capture(connection, add_capture(connection, first.image), LETTER)
    two = read_capture(connection, add_capture(connection, second.image), LETTER)

    assert one.status == two.status == CAPTURE_STATUSES.READ
    assert one.form_id == form.form_id
    services = one.answer((1, None, None))
    assert services is not None
    assert services.values == ("food", "other")
    cell = two.answer((2, 0, 2))
    assert cell is not None
    assert cell.values == ("clothing",)
