"""Typing a date or time as digits, with its separators put in for you."""

from __future__ import annotations

import pytest

from omr_data_collector.constants import ANSWER_TYPES, WRITTEN_DATA_TYPES
from omr_data_collector.models.AnswerSpec import AnswerSpec
from omr_data_collector.ui.date_time_typing import (
    typing_cells,
    typing_hint,
    with_separators,
)


def cells(date_time_format: str) -> tuple[str, ...]:
    spec = AnswerSpec(
        ANSWER_TYPES.WRITTEN,
        data_type=WRITTEN_DATA_TYPES.DATE_TIME,
        date_time_format=date_time_format,
    )
    found = typing_cells(spec)
    assert found is not None
    return found


@pytest.mark.parametrize(
    ("date_time_format", "typed", "shown"),
    [
        ("YYYY/MM/DD", "2", "2"),
        ("YYYY/MM/DD", "2026", "2026"),
        ("YYYY/MM/DD", "20261", "2026/1"),
        ("YYYY/MM/DD", "20261013", "2026/10/13"),
        # A separator typed where it goes is kept; deleting back over it isn't
        # undone ("2026/" back to "2026" stays "2026").
        ("YYYY/MM/DD", "2026/", "2026/"),
        ("YYYY/MM/DD", "2026/10/13", "2026/10/13"),
        # One digit of a month or day, then a separator: padded with a zero.
        ("YYYY/MM/DD", "2026/1/5", "2026/01/5"),
        ("YYYY/MM/DD", "2026/1/", "2026/01/"),
        # Pasted with other separators, or too long.
        ("YYYY/MM/DD", "2026-10-13", "2026/10/13"),
        ("YYYY/MM/DD", "2026101399", "2026/10/13"),
        ("YYYY/MM/DD", "abc", ""),
        ("HH:MM", "1430", "14:30"),
        ("HH:MM", "9:05", "09:05"),
        ("HH:MM", "143", "14:3"),
        ("YYYY/MM/DD HH:MM", "202610131430", "2026/10/13 14:30"),
        ("YYYY/MM/DD HH:MM", "2026-10-13 9:05", "2026/10/13 09:05"),
        ("YYYY/MM/DD HH:MM", "20261013", "2026/10/13"),
        ("YYYY/MM/DD HH:MM", "202610131", "2026/10/13 1"),
    ],
)
def test_digits_are_laid_out_as_the_format(
    date_time_format: str, typed: str, shown: str
) -> None:
    assert with_separators(cells(date_time_format), typed) == shown


def test_only_dates_and_times_are_laid_out() -> None:
    for data_type in (WRITTEN_DATA_TYPES.FREE_TEXT, WRITTEN_DATA_TYPES.ID):
        spec = AnswerSpec(ANSWER_TYPES.WRITTEN, data_type=data_type)
        assert typing_cells(spec) is None
        assert typing_hint(spec) == ""
    assert typing_cells(AnswerSpec.default(ANSWER_TYPES.YES_NO)) is None
    assert typing_cells(None) is None


def test_the_hint_is_the_format() -> None:
    spec = AnswerSpec(
        ANSWER_TYPES.WRITTEN,
        data_type=WRITTEN_DATA_TYPES.DATE_TIME,
        date_time_format="YYYY/MM/DD",
    )
    assert typing_hint(spec) == "YYYY/MM/DD"
