from __future__ import annotations

from omr_data_collector.i18n import tr


def copy_name(name: str, taken_names: set[str]) -> str:
    """A name for a duplicate of ``name``: "Name (copy)", then "Name (copy 2)"."""
    taken = {taken_name.casefold() for taken_name in taken_names}
    candidate = tr("{name} (copy)").format(name=name)
    number = 2
    while candidate.casefold() in taken:
        candidate = tr("{name} (copy {number})").format(name=name, number=number)
        number += 1
    return candidate


def imported_name(name: str, taken_names: set[str]) -> str:
    """A name for an imported block whose name is taken: "Name (imported)", then 2..."""
    taken = {taken_name.casefold() for taken_name in taken_names}
    candidate = tr("{name} (imported)").format(name=name)
    number = 2
    while candidate.casefold() in taken:
        candidate = tr("{name} (imported {number})").format(name=name, number=number)
        number += 1
    return candidate
