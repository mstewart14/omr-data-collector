"""Reads a captured sheet and records what came of it (wiki 60003)."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from omr_data_collector.constants import CAPTURE_STATUSES
from omr_data_collector.engine.scanning import ScanError, scan_sheet
from omr_data_collector.models.Capture import Capture, CapturedAnswer
from omr_data_collector.storage.capture_store import (
    image_path,
    page_image_path,
    save_capture,
)

if TYPE_CHECKING:
    import sqlite3

    from omr_data_collector.engine.scanning import ScannedPage


def read_capture(
    connection: sqlite3.Connection,
    capture: Capture,
    paper_size: str,
    *,
    reframe: bool = False,
) -> Capture:
    """Read ``capture``'s image, store the outcome and return the updated capture.

    A sheet that can be read gets one answer for every place on its page where
    something can be answered, bubbles and handwriting alike, ready for review;
    one that can't is marked unreadable with the reason. ``reframe`` finds the
    page from its QR code ("Read it anyway"; see ``scan_sheet``).
    """
    try:
        scanned = scan_sheet(
            connection,
            image_path(connection, capture),
            paper_size,
            page_image=page_image_path(connection, capture),
            reframe=reframe,
        )
    except ScanError as error:
        updated = replace(
            capture,
            status=CAPTURE_STATUSES.UNREADABLE,
            problem=str(error),
            answers=(),
        )
    else:
        updated = replace(
            capture,
            status=CAPTURE_STATUSES.READ,
            problem="",
            form_id=scanned.identity.form_id,
            form_version=scanned.identity.form_version,
            page=scanned.identity.page,
            answers=captured_answers(scanned),
        )
    save_capture(connection, updated)
    return updated


def captured_answers(scanned: ScannedPage) -> tuple[CapturedAnswer, ...]:
    """Every answer on the page, in reading order, with the bubbles read filled in."""
    read = {
        (answer.block_index, answer.table_row, answer.column): answer
        for answer in scanned.answers
    }
    answers = []
    for region in scanned.template.regions:
        found = read.get(region.key)
        values = found.values if found is not None else ()
        answers.append(
            CapturedAnswer(
                block_index=region.block_index,
                table_row=region.table_row,
                column=region.column,
                scanned=values,
                values=values,
                problem=found.problem if found is not None else "",
            )
        )
    return tuple(answers)
