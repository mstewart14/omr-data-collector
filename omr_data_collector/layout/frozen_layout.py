"""A printed version's whole layout, kept so every copy prints where the first did.

The first printing of a version stores its page templates for scanning
(``omr_template.printed_layout``), and with them this: where every block,
bubble, box and table cell went. Printing the version again draws from it
rather than laying the form out afresh, so a typeface that's missing on another
computer, or measures a little differently there, can change how the text looks
but never where anything is, and sheets printed anywhere scan alike.

Blocks are stored by their place in the version's definition, which never
changes once printed. A stored layout may come from a form file made elsewhere,
so reading one checks every value, and a layout that doesn't fit the form is
ignored in favour of a fresh one.
"""

from __future__ import annotations

import dataclasses
import math
import types
from typing import TYPE_CHECKING, Any, Union, get_args, get_origin, get_type_hints

from PySide6.QtGui import QPageLayout

from omr_data_collector.i18n import tr
from omr_data_collector.layout import form_layout, table_layout
from omr_data_collector.layout.form_layout import FormLayout, layout_form
from omr_data_collector.layout.page_setup import page_layout_for
from omr_data_collector.layout.text import has_family
from omr_data_collector.models.Form import FormBlock
from omr_data_collector.models.FormFont import FormFont

if TYPE_CHECKING:
    from omr_data_collector.models.Form import Form

FROZEN_LAYOUT_KEY = "layout"
# Millimetres: far beyond any page, so a crafted file can't ask for absurd sizes.
MAX_MM = 10_000
MAX_ITEMS = 10_000
# Paper sizes match to well within a printer's own accuracy.
PAPER_TOLERANCE_MM = 0.05

# Every type a layout is made of, by name, for reading its fields' annotations.
_NAMESPACE = {
    **vars(form_layout),
    **vars(table_layout),
    "FormFont": FormFont,
    "FormBlock": FormBlock,
}


class _NotALayoutError(ValueError):
    """A stored layout that isn't one this app wrote, or doesn't fit the form."""


def frozen_layout(layout: FormLayout) -> dict[str, Any]:
    """``layout`` as JSON, its blocks named by their place in the form."""
    return _to_json(layout)


def thawed_layout(data: object, form: Form) -> FormLayout | None:
    """The layout stored for ``form``'s printed version, or None if unusable."""
    try:
        layout = _from_json(FormLayout, data, form)
    except (_NotALayoutError, KeyError, TypeError, IndexError):
        return None
    if not isinstance(layout, FormLayout) or not layout.pages:
        return None
    return layout


def layout_to_print(
    form: Form, paper_size: str, stored: dict[str, Any] | None
) -> tuple[FormLayout, bool]:
    """The layout to print ``form`` from, and whether it is the frozen one.

    A printed version prints from the layout its first printing stored, as long
    as it was for this paper; anything else is laid out now.
    """
    if stored is not None:
        frozen = thawed_layout(stored.get(FROZEN_LAYOUT_KEY), form)
        if frozen is not None and _same_paper(frozen, form, paper_size):
            return frozen, True
    return layout_form(form, paper_size), False


def frozen_warnings(layout: FormLayout, version: int) -> tuple[str, ...]:
    """Problems to mention before printing a frozen layout on this computer."""
    if has_family(layout.font):
        return ()
    return (
        tr(
            'The typeface "{family}" isn\'t installed on this computer, so the '
            "text prints in another one. Everything stays where version {version} "
            "first printed it, so sheets still scan the same."
        ).format(family=layout.font.family, version=version),
    )


def _same_paper(layout: FormLayout, form: Form, paper_size: str) -> bool:
    paper = page_layout_for(paper_size, form.orientation).fullRect(
        QPageLayout.Unit.Millimeter
    )
    return (
        abs(paper.width() - layout.paper_width_mm) < PAPER_TOLERANCE_MM
        and abs(paper.height() - layout.paper_height_mm) < PAPER_TOLERANCE_MM
    )


def _to_json(value: object) -> Any:  # noqa: ANN401 (any JSON value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _to_json(getattr(value, field.name))
            for field in dataclasses.fields(value)
            # A placed block names its block by ``index``.
            if field.name != "block"
        }
    if isinstance(value, (tuple, list)):
        return [_to_json(item) for item in value]
    return value


def _from_json(kind: Any, data: object, form: Form) -> Any:  # noqa: ANN401, C901, PLR0911
    """``data`` read back as ``kind``, checking it against the type all the way."""
    origin = get_origin(kind)
    if origin in {Union, types.UnionType}:
        options = get_args(kind)
        if data is None and type(None) in options:
            return None
        (other,) = [option for option in options if option is not type(None)]
        return _from_json(other, data, form)
    if origin is tuple:
        item_kind, _ = get_args(kind)
        if not isinstance(data, list) or len(data) > MAX_ITEMS:
            raise _NotALayoutError
        return tuple(_from_json(item_kind, item, form) for item in data)
    if kind is float:
        if (
            isinstance(data, bool)
            or not isinstance(data, (int, float))
            or not math.isfinite(data)
            or abs(data) > MAX_MM
        ):
            raise _NotALayoutError
        return float(data)
    if kind is int:
        if isinstance(data, bool) or not isinstance(data, int) or abs(data) > MAX_MM:
            raise _NotALayoutError
        return data
    if kind in {str, bool}:
        if not isinstance(data, kind):
            raise _NotALayoutError
        return data
    if dataclasses.is_dataclass(kind) and isinstance(kind, type):
        return _dataclass_from_json(kind, data, form)
    raise _NotALayoutError


def _dataclass_from_json(kind: type, data: object, form: Form) -> object:
    if not isinstance(data, dict):
        raise _NotALayoutError
    hints = get_type_hints(kind, globalns=_NAMESPACE)
    values: dict[str, Any] = {}
    for field in dataclasses.fields(kind):
        if field.name == "block":
            continue
        if field.name not in data:
            # Added since some layouts were stored: those keep its default.
            if (
                field.default is dataclasses.MISSING
                and field.default_factory is dataclasses.MISSING
            ):
                raise _NotALayoutError
            continue
        values[field.name] = _from_json(hints[field.name], data[field.name], form)
    if "block" in {field.name for field in dataclasses.fields(kind)}:
        index = values["index"]
        if not 0 <= index < len(form.blocks):
            raise _NotALayoutError
        values["block"] = form.blocks[index]
    return kind(**values)
