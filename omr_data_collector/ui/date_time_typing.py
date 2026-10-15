"""Typing a date or time as digits only: the ``/``, ``:`` and space go in by themselves.

The separators are printed on the form, so the person keying in what was written
only types its digits. Typing a separator after one digit of a month, day,
hour or minute pads it with a zero ("9:" for "09:"), and pasting a value
written with other separators ("2026-10-13") keeps its parts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omr_data_collector.constants import ANSWER_TYPES, WRITTEN_DATA_TYPES
from omr_data_collector.ui.AnswerFields import date_time_format_labels

if TYPE_CHECKING:
    from PySide6.QtWidgets import QLineEdit

    from omr_data_collector.models.AnswerSpec import AnswerSpec

Cells = tuple[str, ...]


def typing_cells(spec: AnswerSpec | None) -> Cells | None:
    """The format typing ``spec``'s answer is laid out in: dates and times only."""
    if (
        spec is None
        or spec.answer_type != ANSWER_TYPES.WRITTEN
        or spec.data_type != WRITTEN_DATA_TYPES.DATE_TIME
    ):
        return None
    return spec.written_cells()


def typing_hint(spec: AnswerSpec | None) -> str:
    """What to show in an empty box for ``spec``'s answer: a date or time's format."""
    if spec is None or typing_cells(spec) is None:
        return ""
    return date_time_format_labels()[spec.date_time_format]


def _parts(cells: Cells) -> tuple[list[int], list[str]]:
    """The digit count of each part of a format, and the separator after each."""
    sizes: list[int] = []
    separators: list[str] = []
    pending = ""
    for cell in cells:
        if cell:
            pending += cell
            continue
        if pending or not sizes:
            if sizes:
                separators.append(pending)
            sizes.append(0)
            pending = ""
        sizes[-1] += 1
    return sizes, separators


def with_separators(cells: Cells, text: str) -> str:
    """``text`` as typed so far, laid out as the format ``cells`` prints it.

    ``cells`` is ``AnswerSpec.written_cells()``: ``""`` for each digit, the
    separator printed there otherwise.
    Anything not a digit after one digit of a pair ends the pair, padded with a
    zero, and is otherwise ignored; digits past the end of the format are
    dropped. A separator is only added before a digit that follows it, or where
    one was typed, so deleting back over it isn't undone at once.
    """
    sizes, separators = _parts(cells)
    filled: list[str] = [""] * len(sizes)
    part = 0
    for character in text:
        if part >= len(sizes):
            break
        if character.isdigit() and character.isascii():
            filled[part] += character
            if len(filled[part]) == sizes[part]:
                part += 1
        elif len(filled[part]) == 1 and sizes[part] == 2:
            # A separator typed after one digit of a pair ends it: "9" is "09".
            filled[part] = "0" + filled[part]
            part += 1
    typed = [digits for digits in filled if digits]
    result = "".join(
        digits + (separators[index] if index < len(typed) - 1 else "")
        for index, digits in enumerate(typed)
    )
    ends_with_separator = bool(text) and not text[-1].isdigit()
    if ends_with_separator and len(typed) == part < len(sizes) and typed:
        result += separators[part - 1]
    return result


def fill_separators(line_edit: QLineEdit, cells: Cells | None) -> None:
    """Lay out what's been typed in ``line_edit`` as a date/time (if ``cells``).

    Call it from the line edit's ``textEdited``, before reading its text. The
    cursor stays after the same digit it was after.
    """
    if not cells:
        return
    text = line_edit.text()
    laid_out = with_separators(cells, text)
    if laid_out == text:
        return
    cursor = line_edit.cursorPosition()
    digits_before = sum(1 for character in text[:cursor] if character.isdigit())
    position = len(laid_out)
    if cursor < len(text):
        seen = 0
        for index, character in enumerate(laid_out):
            if seen == digits_before:
                position = index
                break
            seen += character.isdigit()
    line_edit.setText(laid_out)
    line_edit.setCursorPosition(position)
