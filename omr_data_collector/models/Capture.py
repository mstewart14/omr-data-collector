from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from omr_data_collector.constants import CAPTURE_STATUSES


@dataclass(frozen=True)
class CapturedAnswer:
    """One answer on a captured page: as read from the sheet, and as reviewed.

    A question's answer has no ``table_row`` or ``column``; a table cell's has
    both. ``scanned`` holds the saved values of the bubbles marked (empty for a
    written answer, which a person keys in); ``values`` starts as ``scanned``
    and holds what the person reviewing it settled on. ``problem`` is what the
    reading noticed, such as two bubbles marked where one is allowed.
    """

    block_index: int
    table_row: int | None = None
    column: int | None = None
    scanned: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    problem: str = ""

    @property
    def key(self) -> tuple[int, int | None, int | None]:
        return self.block_index, self.table_row, self.column

    def to_dict(self) -> dict[str, Any]:
        return {
            "blockIndex": self.block_index,
            "tableRow": self.table_row,
            "column": self.column,
            "scanned": list(self.scanned),
            "values": list(self.values),
            "problem": self.problem,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapturedAnswer:
        return cls(
            block_index=data["blockIndex"],
            table_row=data.get("tableRow"),
            column=data.get("column"),
            scanned=tuple(data.get("scanned", ())),
            values=tuple(data.get("values", ())),
            problem=data.get("problem", ""),
        )


@dataclass(frozen=True)
class Capture:
    """A photo or scan of one filled-in page, and the data read from it.

    ``file_name`` is the app's own copy of the image, in the captures folder
    (``capture_store.captures_dir``); ``original_name`` is what it was called
    when added. The form, version and page come from the page's QR code once
    it has been read.
    """

    capture_id: str
    file_name: str
    original_name: str
    content_hash: str
    status: str = CAPTURE_STATUSES.WAITING
    problem: str = ""
    form_id: str | None = None
    form_version: int | None = None
    page: int | None = None
    answers: tuple[CapturedAnswer, ...] = field(default=())
    added_at: str = ""

    @property
    def page_image_name(self) -> str:
        """The straightened page saved when it was read, beside the image."""
        return f"{self.capture_id}-page.jpg"

    def answer(self, key: tuple[int, int | None, int | None]) -> CapturedAnswer | None:
        return next((answer for answer in self.answers if answer.key == key), None)
