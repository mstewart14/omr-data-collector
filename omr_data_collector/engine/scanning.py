"""Reads a photo or scan of a filled-in page: which form it is, and what was marked.

The page's QR code names the form, version and page; that version's stored page
template (saved when it was printed) tells OMRChecker where every bubble is, and
says which answer each OMRChecker field belongs to. OMRChecker straightens the
page and measures the bubbles, working on a copy of the image in a working
directory; ``engine.marks`` decides which are marked.
"""

from __future__ import annotations

import copy
import json
import logging
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from omr_data_collector.constants import ANSWER_TYPES, QR_PAYLOAD_TYPES
from omr_data_collector.engine.alignment import (
    PaperFrame,
    misalignment,
    reframed,
    turn_upright,
)
from omr_data_collector.engine.marks import FieldMarks, MarksUnclearError, read_marks
from omr_data_collector.engine.runner import (
    CONFIG_FILE_NAME,
    TEMPLATE_FILE_NAME,
    measure_page,
)
from omr_data_collector.i18n import tr
from omr_data_collector.identity.qr_code import find_qr_codes, parse_payload
from omr_data_collector.layout.form_layout import layout_form
from omr_data_collector.layout.omr_template import (
    MARKER_FILE_NAME,
    TEMPLATE_PX_PER_MM,
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
    from collections.abc import Iterator

    from omr_data_collector.models.AnswerSpec import AnswerSpec
    from omr_data_collector.models.Form import Form

# Settings for OMRChecker: no windows or debug images.
OMR_CONFIG = {"outputs": {"show_image_level": 0, "save_image_level": 0}}
# The QR reader only ever sees pictures at most this wide. It reads a page's
# code well at this size, and wider pictures can take it minutes to give up on
# when there's no code it can read: a blurred 4000-pixel photo ran for over ten
# minutes, where 2000 pixels took two seconds.
QR_MAX_WIDTH = 2000
# If the code isn't found at the first size, it gets another try this wide.
QR_RETRY_WIDTH = 1200
# The first step of straightening, finding the sheet's edges against what it
# lies on, fails on a scan (no background) or a cluttered one; the page is then
# straightened on its corner markers alone.
PAGE_EDGES_STEP = "CropPage"
# How far around where the form puts its code to look for it again, enlarged,
# on a straightened page.
CODE_SEARCH_REACH_MM = 25.0

logger = logging.getLogger(__name__)


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
    empty, and none when it can't be told). A problem (two bubbles marked where
    only one is allowed, or a bubble neither clearly marked nor empty) is for a
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


@dataclass(frozen=True)
class FoundCode:
    """A form QR code found in a picture: what it says, and where its corners are.

    ``corners`` are in the picture's pixels, in the code's own order (top-left,
    top-right, bottom-right, bottom-left), however the picture is turned.
    """

    identity: SheetIdentity
    corners: np.ndarray


def read_sheet_identity(image: np.ndarray) -> SheetIdentity:
    """Find and decode the form QR code in a photo or scan.

    Raises:
        ScanError: No form QR code from this app could be read.
    """
    return find_form_code(image).identity


def find_form_code(image: np.ndarray) -> FoundCode:
    """Find the form QR code in a photo or scan, and where it is.

    Raises:
        ScanError: No form QR code from this app could be read.
    """
    gray = _gray(image)
    width = gray.shape[1]
    sizes = [min(width, QR_MAX_WIDTH)]
    if width > QR_RETRY_WIDTH:
        sizes.append(QR_RETRY_WIDTH)
    if width < QR_MAX_WIDTH:
        # Codes whose squares are only a few pixels wide are often missed;
        # enlarged, a small or soft photo's code often reads.
        sizes.append(min(width * 2, QR_MAX_WIDTH))
    for size in sizes:
        found = _form_code_in(_resized_to_width(gray, size), width / size)
        if found is not None:
            return found
    msg = tr(
        "Couldn't read the form's QR code (top right of the page). Make sure the "
        "whole page is in the picture, in focus and evenly lit."
    )
    raise ScanError(msg)


def _form_code_in(gray: np.ndarray, scale: float = 1.0) -> FoundCode | None:
    """The first form code the reader finds, its corners multiplied by ``scale``."""
    for text, corners in find_qr_codes(gray):
        try:
            payload = parse_payload(text)
        except ValueError:
            continue
        if payload["type"] == QR_PAYLOAD_TYPES.FORM:
            return FoundCode(
                identity=SheetIdentity(
                    organization_id=payload["organizationId"],
                    form_id=payload["formId"],
                    form_version=payload["formVersion"],
                    page=payload["page"],
                ),
                corners=np.asarray(corners, dtype=np.float64) * scale,
            )
    return None


def _gray(image: np.ndarray) -> np.ndarray:
    return image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _resized_to_width(image: np.ndarray, width: int) -> np.ndarray:
    height, current = image.shape
    if width == current:
        return image
    interpolation = cv2.INTER_AREA if width < current else cv2.INTER_CUBIC
    return cv2.resize(
        image, (width, round(height * width / current)), interpolation=interpolation
    )


def scan_sheet(  # noqa: PLR0913 (where to read from, keep and look)
    connection: sqlite3.Connection,
    image_path: Path,
    paper_size: str,
    work_dir: Path | None = None,
    page_image: Path | None = None,
    *,
    reframe: bool = False,
) -> ScannedPage:
    """Identify a filled-in page and read its bubbles.

    ``page_image`` is where to save the straightened page, as OMRChecker saw it
    (see ``read_page``).

    ``paper_size`` is only used for a version stored before page templates were
    kept with printed versions; otherwise the stored templates are used, so the
    sheet is read exactly as it was printed.

    A picture taken sideways or upside down is turned upright first, by its QR
    code. ``reframe`` ("Read it anyway") also finds the page from its QR code
    rather than its edges, for a sheet printed at another size or orientation
    than its form, such as a landscape form shrunk onto portrait paper.

    Raises:
        ScanError: The image, its QR code or its corner markers couldn't be read,
            the page didn't line up with its form, or it is from a form or
            version this computer doesn't have.
    """
    image = cv2.imread(str(image_path))
    if image is None:
        msg = tr("Couldn't open {file} as an image.").format(file=image_path.name)
        raise ScanError(msg)
    found = find_form_code(image)
    identity = found.identity
    form = load_form_version(connection, identity.form_id, identity.form_version)
    if form is None:
        msg = tr(
            "This sheet is from version {version} of a form that isn't on this "
            "computer."
        ).format(version=identity.form_version)
        raise ScanError(msg)
    template = _stored_page_template(connection, form, identity, paper_size)
    upright, corners = turn_upright(image, found.corners)
    picture: np.ndarray | None = None if upright is image else upright
    if reframe:
        picture = reframed(
            upright, corners, PaperFrame.from_template(template.template), identity
        )
    answers = read_page(
        image_path,
        form,
        template,
        work_dir,
        page_image,
        identity=identity,
        picture=picture,
        find_edges=not reframe,
    )
    return ScannedPage(identity=identity, form=form, template=template, answers=answers)


def read_page(  # noqa: PLR0913 (what to read, against what, and where to work)
    image_path: Path,
    form: Form,
    template: PageTemplate,
    work_dir: Path | None = None,
    page_image: Path | None = None,
    *,
    identity: SheetIdentity | None = None,
    picture: np.ndarray | None = None,
    find_edges: bool = True,
) -> tuple[ScannedAnswer, ...]:
    """Straighten one page image with OMRChecker and read its bubbles.

    ``picture``, if given, is read instead of the file at ``image_path`` (a
    picture turned upright or re-framed). ``work_dir`` keeps OMRChecker's files
    (for looking into a problem); by default a temporary directory is used and
    removed. ``page_image`` is where to save the page straightened on its corner
    markers: at template scale, so ``PageTemplate.regions`` locate each answer
    in it.

    The page is first straightened as its template says, finding the sheet's
    edges and then its markers; if that fails, or ``find_edges`` is False, on
    its markers alone. With ``identity`` (the page's QR code), a straightened
    page must have its code where the form puts it, or its bubbles would be read
    in the wrong places.

    Raises:
        ScanError: OMRChecker couldn't find the page or its corner markers, the
            page didn't line up with its form, or too many bubbles were neither
            clearly marked nor clearly empty.
    """
    with _working_directory(work_dir) as work:
        input_dir = work / "input"
        shutil.rmtree(input_dir, ignore_errors=True)
        input_dir.mkdir(parents=True)
        cv2.imwrite(str(input_dir / MARKER_FILE_NAME), marker_image())
        (input_dir / CONFIG_FILE_NAME).write_text(json.dumps(OMR_CONFIG))
        if picture is None:
            sheet = input_dir / f"sheet{image_path.suffix.lower()}"
            shutil.copyfile(image_path, sheet)
        else:
            sheet = input_dir / "sheet.png"
            cv2.imwrite(str(sheet), picture)
        expected = (
            PaperFrame.from_template(template.template).code_corners_template_px(
                identity
            )
            if identity is not None
            else None
        )
        steps = [template.template] if find_edges else []
        if PAGE_EDGES_STEP in _step_names(template.template):
            steps.append(_without_page_edges(template.template))
        lined_up_wrong = False
        for number, steps_template in enumerate(steps):
            output_dir = work / f"output{number}"
            shutil.rmtree(output_dir, ignore_errors=True)
            (input_dir / TEMPLATE_FILE_NAME).write_text(json.dumps(steps_template))
            try:
                measured = measure_page(input_dir, sheet, output_dir)
            except Exception:  # OMRChecker raises bare Exceptions.
                logger.info("Straightening attempt %d failed", number, exc_info=True)
                continue
            if expected is not None:
                problem = misalignment(
                    _code_on_page(_gray(measured.image), expected), expected
                )
                if problem is not None:
                    logger.info("Straightening attempt %d: %s", number, problem)
                    lined_up_wrong = True
                    continue
            break
        else:
            raise ScanError(
                _misaligned_message() if lined_up_wrong else _unreadable_message()
            )
    if page_image is not None:
        page_image.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(page_image), measured.image)
    try:
        marks = read_marks(measured)
    except MarksUnclearError as error:
        msg = tr(
            "Couldn't tell the marked bubbles from the empty ones on this page. "
            "Take the picture again flat, in focus and in even light, and check "
            "the bubbles are filled in firmly."
        )
        raise ScanError(msg) from error
    return interpret(form, template, marks)


def _code_on_page(page: np.ndarray, expected: np.ndarray) -> np.ndarray | None:
    """The form code's corners on a straightened page, if it can be found.

    Small and soft at template scale, the code is looked for again enlarged,
    but only around where the form puts it: enlarging the whole page makes the
    reader slow to give up, and a code anywhere else fails the check anyway.
    """
    found = _form_code_in(page)
    if found is not None:
        return found.corners
    reach = CODE_SEARCH_REACH_MM * TEMPLATE_PX_PER_MM
    left, top = np.maximum(expected.min(axis=0) - reach, 0).astype(int)
    right, bottom = (expected.max(axis=0) + reach).astype(int)
    around = page[top:bottom, left:right]
    if around.size == 0:
        return None
    found = _form_code_in(
        cv2.resize(around, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC), 0.5
    )
    return np.add(found.corners, (left, top)) if found is not None else None


@contextmanager
def _working_directory(work_dir: Path | None) -> Iterator[Path]:
    if work_dir is not None:
        yield work_dir
        return
    # Should a file still be open (Windows won't delete one), the operating
    # system clears it up later.
    with tempfile.TemporaryDirectory(
        prefix="omr-scan-", ignore_cleanup_errors=True
    ) as temporary:
        yield Path(temporary)


def _step_names(template: dict[str, Any]) -> list[str]:
    return [step["name"] for step in template.get("preProcessors", [])]


def _without_page_edges(template: dict[str, Any]) -> dict[str, Any]:
    """The template with straightening on the corner markers alone."""
    changed = copy.deepcopy(template)
    changed["preProcessors"] = [
        step for step in changed["preProcessors"] if step["name"] != PAGE_EDGES_STEP
    ]
    return changed


def interpret(
    form: Form, template: PageTemplate, marks: dict[str, FieldMarks]
) -> tuple[ScannedAnswer, ...]:
    """Turn each field's marked bubbles into answers.

    An answer with a bubble that couldn't be told marked or empty keeps only
    the clearly marked ones and says so, for a person to check.
    """
    marked: dict[tuple[int, int | None, int | None], list[int]] = {}
    unclear: set[tuple[int, int | None, int | None]] = set()
    for label, field in template.fields.items():
        key = (field.block_index, field.table_row, field.column)
        found = marks.get(label, FieldMarks())
        if found.unclear:
            unclear.add(key)
        marked.setdefault(key, []).extend(
            field.first_choice + index for index in found.marked
        )
    answers = []
    for (block_index, table_row, column), choices in marked.items():
        key = (block_index, table_row, column)
        spec = _answer_spec(form, block_index, column)
        values = tuple(
            spec.choices[index].output or spec.choices[index].label
            for index in sorted(set(choices))
            if index < len(spec.choices)
        )
        if spec.answer_type == ANSWER_TYPES.YES_NO and key not in unclear:
            # One bubble: marked saves the first choice, empty the second.
            when_marked, when_empty = spec.choices
            values = ((when_marked if values else when_empty).output,)
        problem = ""
        if key in unclear:
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
        "all four corners are in the picture, and the page lies flat. If the sheet "
        "was printed at another size or orientation than its form, choose Read it "
        "anyway."
    )


def _misaligned_message() -> str:
    return tr(
        "The page didn't line up with its form: its QR code wasn't where the form "
        "puts it, so its answers can't be found. If the sheet was printed at "
        "another size or orientation than its form (a landscape form printed on "
        "portrait paper, say), choose Read it anyway."
    )
