from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from omr_data_collector.constants import CAPTURE_STATUSES

if TYPE_CHECKING:
    from omr_data_collector.models.AnswerSpec import AnswerSpec

# Captures whose answers have been read, so can be compared.
READ_STATUSES = {CAPTURE_STATUSES.READ, CAPTURE_STATUSES.SAVED}


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

    def changed_by_hand(self, spec: AnswerSpec) -> bool:
        """Whether the person checking it changed what its bubbles read as.

        Typing in a handwritten answer isn't a change: nothing was read there.
        """
        return bool(spec.choices) and set(self.values) != set(self.scanned)

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

    def looks_like(self, other: Capture) -> bool:
        """Whether ``other`` looks like another picture of this same filled-in sheet.

        Both are the same page of the same form version, with every bubble
        read the same and at least one marked, and no answer typed in
        differently on each (two different dates, say). Different people can
        mark a short form alike, so this is only ever a warning.
        """
        if (
            other.capture_id == self.capture_id
            or self.status not in READ_STATUSES
            or other.status not in READ_STATUSES
            or (self.form_id, self.form_version, self.page)
            != (other.form_id, other.form_version, other.page)
        ):
            return False
        mine = {answer.key: answer for answer in self.answers}
        theirs = {answer.key: answer for answer in other.answers}
        if mine.keys() != theirs.keys() or not any(a.scanned for a in self.answers):
            return False
        for key, answer in mine.items():
            match = theirs[key]
            if answer.scanned != match.scanned:
                return False
            typed_differently = (
                not answer.scanned
                and answer.values
                and match.values
                and answer.values != match.values
            )
            if typed_differently:
                return False
        return True
