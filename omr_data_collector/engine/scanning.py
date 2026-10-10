"""Reads a photo or scan of a filled-in page: which form it is, and what was marked.

The page's QR code names the form, version and page; that version's stored page
template (saved when it was printed) tells OMRChecker where every bubble is, and
says which answer each OMRChecker field belongs to. OMRChecker works on a copy of
the image in a working directory, since it moves sheets it can't read.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import cv2

from omr_data_collector.constants import ANSWER_TYPES, QR_PAYLOAD_TYPES
from omr_data_collector.engine.runner import run_omr
from omr_data_collector.i18n import tr
from omr_data_collector.identity.qr_code import parse_payload, read_qr_codes
from omr_data_collector.layout.form_layout import layout_form
from omr_data_collector.layout.omr_template import (
    MARKER_FILE_NAME,
    PageTemplate,
    marker_image,
    page_template,
)
from omr_data_collector.models.Question import Question
from omr_data_collector.models.SheetDetails import SheetDetails
from omr_data_collector.models.TableBlock import TableBlock
from omr_data_collector.storage.form_store import (
    load_form_version,
    load_printed_layout,
)

if TYPE_CHECKING:
    import sqlite3

    import numpy as np

    from omr_data_collector.models.AnswerSpec import AnswerSpec
    from omr_data_collector.models.Form import Form

# Settings for OMRChecker: no windows or debug images, and sheets with several
# bubbles marked in a field are still read (this app flags them itself).
OMR_CONFIG = {
    "outputs": {
        "show_image_level": 0,
        "save_image_level": 0,
        "filter_out_multimarked_files": False,
    }
}
# The QR reader only ever sees pictures at most this wide. It reads a page's
# code well at this size, and wider pictures can take it minutes to give up on
# when there's no code it can read: a blurred 4000-pixel photo ran for over ten
# minutes, where 2000 pixels took two seconds.
QR_MAX_WIDTH = 2000
# If the code isn't found at the first size, it gets another try this wide.
QR_RETRY_WIDTH = 1200


class ScanError(Exception):
    """A sheet that couldn't be read, with a message to show the person scanning."""


@dataclass(frozen=True)
class SheetIdentity:
    """What a page's QR code says it is."""

    organization_id: str
    form_id: str
    form_version: int
    page: int


@dataclass(frozen=True)
class ScannedAnswer:
    """The bubbles marked for one question, or one table cell.

    ``values`` are the marked choices' saved values, in choice order (a yes/no
    answer's one bubble saves its first value when marked, its second when
    empty). A problem (two bubbles marked where only one is allowed) is for a
    person to review.
    """

    block_index: int
    values: tuple[str, ...]
    table_row: int | None = None
    column: int | None = None
    problem: str = ""


@dataclass(frozen=True)
class ScannedPage:
    identity: SheetIdentity
    form: Form
    # The page as printed: its fields, and where each answer is.
    template: PageTemplate
    answers: tuple[ScannedAnswer, ...]


def read_sheet_identity(image: np.ndarray) -> SheetIdentity:
    """Find and decode the form QR code in a photo or scan.

    Raises:
        ScanError: No form QR code from this app could be read.
    """
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    candidates = [_resized_to_width(gray, min(width, QR_MAX_WIDTH))]
    if width > QR_RETRY_WIDTH:
        candidates.append(_resized_to_width(gray, QR_RETRY_WIDTH))
    if width < QR_MAX_WIDTH:
        # Codes whose squares are only a few pixels wide are often missed;
        # enlarged, a small or soft photo's code often reads.
        candidates.append(_resized_to_width(gray, min(width * 2, QR_MAX_WIDTH)))
    for candidate in candidates:
        for text in read_qr_codes(candidate):
            try:
                payload = parse_payload(text)
            except ValueError:
                continue
            if payload["type"] == QR_PAYLOAD_TYPES.FORM:
                return SheetIdentity(
                    organization_id=payload["organizationId"],
                    form_id=payload["formId"],
                    form_version=payload["formVersion"],
                    page=payload["page"],
                )
    msg = tr(
        "Couldn't read the form's QR code (top right of the page). Make sure the "
        "whole page is in the picture, in focus and evenly lit."
    )
    raise ScanError(msg)


def _resized_to_width(image: np.ndarray, width: int) -> np.ndarray:
    height, current = image.shape
    if width == current:
        return image
    interpolation = cv2.INTER_AREA if width < current else cv2.INTER_CUBIC
    return cv2.resize(
        image, (width, round(height * width / current)), interpolation=interpolation
    )


def scan_sheet(
    connection: sqlite3.Connection,
    image_path: Path,
    paper_size: str,
    work_dir: Path | None = None,
    page_image: Path | None = None,
) -> ScannedPage:
    """Identify a filled-in page and read its bubbles.

    ``page_image`` is where to save the straightened page, as OMRChecker saw it
    (see ``read_page``).

    ``paper_size`` is only used for a version stored before page templates were
    kept with printed versions; otherwise the stored templates are used, so the
    sheet is read exactly as it was printed.

    Raises:
        ScanError: The image, its QR code or its corner markers couldn't be read,
            or it is from a form or version this computer doesn't have.
    """
    image = cv2.imread(str(image_path))
    if image is None:
        msg = tr("Couldn't open {file} as an image.").format(file=image_path.name)
        raise ScanError(msg)
    identity = read_sheet_identity(image)
    form = load_form_version(connection, identity.form_id, identity.form_version)
    if form is None:
        msg = tr(
            "This sheet is from version {version} of a form that isn't on this "
            "computer."
        ).format(version=identity.form_version)
        raise ScanError(msg)
    template = _stored_page_template(connection, form, identity, paper_size)
    answers = read_page(image_path, form, template, work_dir, page_image)
    return ScannedPage(identity=identity, form=form, template=template, answers=answers)


def read_page(
    image_path: Path,
    form: Form,
    template: PageTemplate,
    work_dir: Path | None = None,
    page_image: Path | None = None,
) -> tuple[ScannedAnswer, ...]:
    """Run OMRChecker on one page image with its template.

    ``work_dir`` keeps OMRChecker's files (for looking into a problem); by default
    a temporary directory is used and removed. ``page_image`` is where to save
    the page straightened on its corner markers, with the marks OMRChecker found
    drawn on it: at template scale, so ``PageTemplate.regions`` locate each
    answer in it.

    Raises:
        ScanError: OMRChecker couldn't find the page or its corner markers.
    """
    if work_dir is None:
        # OMRChecker leaves its ErrorFiles.csv open after a sheet it can't read,
        # which Windows won't delete; the operating system clears it up later.
        with tempfile.TemporaryDirectory(
            prefix="omr-scan-", ignore_cleanup_errors=True
        ) as temporary:
            return read_page(image_path, form, template, Path(temporary), page_image)
    input_dir = work_dir / "input"
    output_dir = work_dir / "output"
    shutil.rmtree(input_dir, ignore_errors=True)
    shutil.rmtree(output_dir, ignore_errors=True)
    input_dir.mkdir(parents=True)
    (input_dir / "template.json").write_text(json.dumps(template.template))
    (input_dir / "config.json").write_text(json.dumps(OMR_CONFIG))
    cv2.imwrite(str(input_dir / MARKER_FILE_NAME), marker_image())
    shutil.copyfile(image_path, input_dir / f"sheet{image_path.suffix.lower()}")
    try:
        rows = run_omr(input_dir, output_dir)
    except Exception as error:  # OMRChecker raises bare Exceptions.
        raise ScanError(_unreadable_message()) from error
    if not rows:
        raise ScanError(_unreadable_message())
    if page_image is not None:
        checked = next(output_dir.glob("**/CheckedOMRs/sheet.*"), None)
        if checked is not None:
            page_image.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(checked, page_image)
    return interpret(form, template, rows[0])


def interpret(
    form: Form, template: PageTemplate, row: dict[str, str]
) -> tuple[ScannedAnswer, ...]:
    """Turn OMRChecker's values (the marked bubbles' values, per field) into answers."""
    marked: dict[tuple[int, int | None, int | None], list[int]] = {}
    unclear: set[tuple[int, int | None, int | None]] = set()
    for label, field in template.fields.items():
        key = (field.block_index, field.table_row, field.column)
        choices = field.choices_marked(row.get(label, ""))
        if choices is None:
            unclear.add(key)
            choices = []
        marked.setdefault(key, []).extend(choices)
    answers = []
    for (block_index, table_row, column), choices in marked.items():
        spec = _answer_spec(form, block_index, column)
        values = tuple(
            spec.choices[index].output or spec.choices[index].label
            for index in sorted(set(choices))
            if index < len(spec.choices)
        )
        if spec.answer_type == ANSWER_TYPES.YES_NO:
            # One bubble: marked saves the first choice, empty the second.
            when_marked, when_empty = spec.choices
            values = ((when_marked if values else when_empty).output,)
        problem = ""
        if (block_index, table_row, column) in unclear:
            problem = tr("Couldn't tell which bubbles are marked: check the sheet.")
        elif spec.answer_type == ANSWER_TYPES.ONE_CHOICE and len(values) > 1:
            problem = tr("More than one bubble is marked, but only one is allowed.")
        answers.append(
            ScannedAnswer(
                block_index=block_index,
                values=values,
                table_row=table_row,
                column=column,
                problem=problem,
            )
        )
    return tuple(answers)


def _stored_page_template(
    connection: sqlite3.Connection,
    form: Form,
    identity: SheetIdentity,
    paper_size: str,
) -> PageTemplate:
    stored = load_printed_layout(connection, form.form_id, form.version)
    if stored is not None:
        pages = stored["pages"]
        if not 1 <= identity.page <= len(pages):
            msg = tr(
                "This sheet says it is page {page}, which the form doesn't have."
            ).format(page=identity.page)
            raise ScanError(msg)
        return PageTemplate.from_dict(pages[identity.page - 1])
    layout = layout_form(form, paper_size)
    for page in layout.pages:
        if page.number == identity.page:
            return page_template(layout, page)
    msg = tr("This sheet says it is page {page}, which the form doesn't have.").format(
        page=identity.page
    )
    raise ScanError(msg)


def _answer_spec(form: Form, block_index: int, column: int | None) -> AnswerSpec:
    content = form.blocks[block_index].content
    if isinstance(content, TableBlock) and column is not None:
        return content.columns[column].answer
    if isinstance(content, SheetDetails) and column is not None:
        return content.fields[column].answer
    if isinstance(content, Question):
        return content.answer
    msg = tr("Block {number} of the form has no bubbles.").format(
        number=block_index + 1
    )
    raise ScanError(msg)


def _unreadable_message() -> str:
    return tr(
        "Couldn't find the page's four corner markers (the black dots). Make sure "
        "all four corners are in the picture, and the page lies flat."
    )
