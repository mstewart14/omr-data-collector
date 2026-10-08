from __future__ import annotations


def copy_name(name: str, taken_names: set[str]) -> str:
    """A name for a duplicate of ``name``: "Name (copy)", then "Name (copy 2)"."""
    taken = {taken_name.casefold() for taken_name in taken_names}
    candidate = f"{name} (copy)"
    number = 2
    while candidate.casefold() in taken:
        candidate = f"{name} (copy {number})"
        number += 1
    return candidate
