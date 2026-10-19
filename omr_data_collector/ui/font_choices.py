"""The choices a form's details offer for its typeface, style and text size."""

from __future__ import annotations

from PySide6.QtCore import QLocale
from PySide6.QtGui import QFontDatabase

from omr_data_collector.i18n import tr
from omr_data_collector.layout.text import standard_family
from omr_data_collector.models.FormFont import SIZES

# A family's own name for its plain style, which the "Regular" choice stands for.
REGULAR_STYLES = {"regular", "normal", "book", "roman"}


def points(size: float) -> str:
    """A size in points, as this language writes numbers ("10.5 pt")."""
    return tr("{size} pt").format(size=QLocale().toString(float(size), "g", 4))


def family_choices(current: str) -> list[tuple[str, str]]:
    """Typefaces to offer, as (shown, stored): the standard one, then every family.

    A family the form names but this computer doesn't have stays on the list,
    marked, so opening the form doesn't change it.
    """
    choices = [(tr("Standard font ({family})").format(family=standard_family()), "")]
    families = [
        family
        for family in QFontDatabase.families()
        if not QFontDatabase.isPrivateFamily(family)
    ]
    if current and current not in families:
        choices.append((tr("{family} (not installed)").format(family=current), current))
    choices += [(family, family) for family in families]
    return choices


def style_choices(family: str, current: str) -> list[tuple[str, str]]:
    """The styles of ``family`` ("" for the standard font) to offer.

    "Regular" first, standing for the family's plain style, then its others
    (Light, Bold, Condensed...).
    """
    styles = QFontDatabase.styles(family or standard_family())
    choices = [(tr("Regular"), "")]
    choices += [
        (style, style) for style in styles if style.casefold() not in REGULAR_STYLES
    ]
    if current and all(stored != current for _, stored in choices):
        choices.append((tr("{style} (not installed)").format(style=current), current))
    return choices


def size_choices(current: float) -> list[tuple[str, float]]:
    """Text sizes to offer, in points, with the form's own if it is between them."""
    sizes = sorted({*SIZES, current})
    return [(points(size), size) for size in sizes]
