from __future__ import annotations

import pytest

from omr_data_collector.models.ordering import move_by, move_to

ITEMS = list("abcdef")


@pytest.mark.parametrize(
    ("selected", "offset", "expected", "expected_selected"),
    [
        ([2], -1, "acbdef", [1]),
        ([2], 1, "abdcef", [3]),
        ([1, 3], -1, "badcef", [0, 2]),
        ([1, 3], 1, "acbedf", [2, 4]),
        # A block already at the top stays; the one behind it closes up to it.
        ([0, 2], -1, "acbdef", [0, 1]),
        ([0, 1], -1, "abcdef", [0, 1]),
        ([4, 5], 1, "abcdef", [4, 5]),
        ([3, 5], 1, "abcedf", [4, 5]),
    ],
)
def test_move_by(
    selected: list[int], offset: int, expected: str, expected_selected: list[int]
) -> None:
    result, new_selected = move_by(ITEMS, selected, offset)

    assert "".join(result) == expected
    assert new_selected == expected_selected
    # The selected items are still the ones selected, in their order.
    assert [result[index] for index in new_selected] == [
        ITEMS[index] for index in sorted(selected)
    ]


@pytest.mark.parametrize(
    ("selected", "insert_index", "expected", "expected_selected"),
    [
        ([4], 0, "eabcdf", [0]),
        ([0], 6, "bcdefa", [5]),
        ([0], 2, "bacdef", [1]),
        ([1, 4], 0, "beacdf", [0, 1]),
        ([1, 4], 6, "acdfbe", [4, 5]),
        ([1, 4], 3, "acbedf", [2, 3]),
        # Dropping onto itself changes nothing.
        ([2], 2, "abcdef", [2]),
        ([2], 3, "abcdef", [2]),
        ([], 3, "abcdef", []),
    ],
)
def test_move_to(
    selected: list[int], insert_index: int, expected: str, expected_selected: list[int]
) -> None:
    result, new_selected = move_to(ITEMS, selected, insert_index)

    assert "".join(result) == expected
    assert new_selected == expected_selected


def test_moves_never_lose_or_duplicate_items() -> None:
    for selected in ([0], [5], [0, 5], [1, 2, 3], [0, 2, 4]):
        for insert_index in range(len(ITEMS) + 1):
            result, _ = move_to(ITEMS, selected, insert_index)
            assert sorted(result) == ITEMS
        for offset in (-1, 1):
            result, _ = move_by(ITEMS, selected, offset)
            assert sorted(result) == ITEMS
