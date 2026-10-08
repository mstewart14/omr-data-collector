"""Moving several selected items of a list together, keeping their order."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

T = TypeVar("T")


# TypeVar, not def f[T]() (UP047): that syntax needs Python 3.12; 3.11 is supported.
def move_by(  # noqa: UP047
    items: Sequence[T], selected: Iterable[int], offset: int
) -> tuple[list[T], list[int]]:
    """Move each selected item ``offset`` places (-1 up, 1 down).

    An item stops at the end of the list, and the selected items behind it stop
    with it, so the selection keeps its order and its gaps close up only where
    there is room.

    Returns:
        The reordered items and the selected items' new positions.
    """
    result = list(items)
    chosen = {index for index in selected if 0 <= index < len(result)}
    for index in sorted(chosen, reverse=offset > 0):
        target = index + offset
        if 0 <= target < len(result) and target not in chosen:
            result[index], result[target] = result[target], result[index]
            chosen.remove(index)
            chosen.add(target)
    return result, sorted(chosen)


def move_to(  # noqa: UP047
    items: Sequence[T], selected: Iterable[int], insert_index: int
) -> tuple[list[T], list[int]]:
    """Move the selected items, in order, to just before ``insert_index``.

    ``insert_index`` counts positions in ``items`` as they are before the move
    (``len(items)`` is the end), which is how a drop point is found.

    Returns:
        The reordered items and the moved items' new positions.
    """
    chosen = sorted({index for index in selected if 0 <= index < len(items)})
    if not chosen:
        return list(items), []
    moving = [items[index] for index in chosen]
    staying = [item for index, item in enumerate(items) if index not in set(chosen)]
    position = insert_index - sum(1 for index in chosen if index < insert_index)
    position = max(0, min(position, len(staying)))
    result = staying[:position] + moving + staying[position:]
    return result, list(range(position, position + len(moving)))
