"""Helpers for the app's accessibility requirements.

The target is WCAG 2.2 level AA as it applies to desktop software: everything usable
from the keyboard, every control named for screen readers, status changes announced,
and text contrast of at least 4.5:1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent, QColor, QPalette

if TYPE_CHECKING:
    from collections.abc import Mapping

    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QFormLayout, QLabel, QWidget

# WCAG 2.2 success criterion 1.4.3: normal-size text needs 4.5:1 against its
# background.
MIN_TEXT_CONTRAST = 4.5

# Error reds tried in order. The first suits light backgrounds, the second dark
# ones; on a theme where neither reaches MIN_TEXT_CONTRAST (some high-contrast
# themes), errors fall back to the theme's own text color, and their wording alone
# marks them as errors.
ERROR_COLOR_CANDIDATES = ("#a50e0e", "#ffb4ab")
# How far a band of rows is shaded from the background towards the text, tried
# in order until the text on it stays readable.
BAND_SHADES = (0.12, 0.08, 0.05)


def relative_luminance(color: QColor) -> float:
    """Relative luminance as WCAG defines it, from 0 (black) to 1 (white)."""

    def linear(channel: float) -> float:
        if channel <= 0.04045:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * linear(color.redF())
        + 0.7152 * linear(color.greenF())
        + 0.0722 * linear(color.blueF())
    )


def contrast_ratio(first: QColor, second: QColor) -> float:
    """WCAG contrast ratio between two colors, from 1 (none) to 21 (black on white)."""
    lighter, darker = sorted(
        (relative_luminance(first), relative_luminance(second)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def error_text_color(palette: QPalette) -> QColor:
    """A red for error text that is readable on the palette's window background."""
    background = palette.color(QPalette.ColorRole.Window)
    for candidate in ERROR_COLOR_CANDIDATES:
        color = QColor(candidate)
        if contrast_ratio(color, background) >= MIN_TEXT_CONTRAST:
            return color
    return palette.color(QPalette.ColorRole.WindowText)


def band_color(palette: QPalette) -> QColor:
    """A background for every other group of rows: the list's own, tinted.

    Shaded towards the text color just enough to tell bands apart, and never
    so far that the text on it drops below MIN_TEXT_CONTRAST.
    """
    base = palette.color(QPalette.ColorRole.Base)
    text = palette.color(QPalette.ColorRole.Text)
    for share in BAND_SHADES:
        band = QColor.fromRgbF(
            base.redF() + (text.redF() - base.redF()) * share,
            base.greenF() + (text.greenF() - base.greenF()) * share,
            base.blueF() + (text.blueF() - base.blueF()) * share,
        )
        if contrast_ratio(band, text) >= MIN_TEXT_CONTRAST:
            return band
    return palette.color(QPalette.ColorRole.AlternateBase)


def style_error_label(label: QLabel, palette: QPalette) -> None:
    """Color an error label for the background in ``palette``.

    Pass the containing page's palette, not the label's: once a label has a style
    sheet, its own palette no longer follows theme changes. Call again whenever the
    page's palette changes.
    """
    label.setStyleSheet(f"color: {error_text_color(palette).name()};")


def set_field_error(
    form: QFormLayout, field: QWidget, error_label: QLabel, message: str
) -> None:
    """Show (or with an empty message, clear) a field's error.

    ``error_label`` is in its own row of ``form``, which is hidden while there's no
    error. The message also becomes the field's accessible description, which
    screen readers read along with the field's name when it gets focus.
    """
    error_label.setText(message)
    form.setRowVisible(error_label, bool(message))
    field.setAccessibleDescription(message)


def show_field_errors(
    form: QFormLayout,
    fields: Mapping[str, QWidget],
    error_labels: Mapping[str, QLabel],
    errors: Mapping[str, str],
) -> bool:
    """Show each field's error from ``errors`` and clear the others'.

    Each goes through ``set_field_error``.

    When there are errors, focus moves to the first field in ``fields`` order that
    has one; screen readers then read its name and, from its accessible
    description, the error.

    Returns:
        Whether there were any errors.
    """
    for key, label in error_labels.items():
        set_field_error(form, fields[key], label, errors.get(key, ""))
    first = next((key for key in fields if key in errors), None)
    if first is not None:
        fields[first].setFocus(Qt.FocusReason.OtherFocusReason)
    return bool(errors)


def announce(source: QObject, message: str, *, assertive: bool = False) -> None:
    """Have screen readers speak ``message``, which may not be on screen anywhere.

    Polite announcements wait for the screen reader to finish speaking; assertive
    ones interrupt it, so keep those for things that need attention now.
    """
    event = QAccessibleAnnouncementEvent(source, message)
    event.setPoliteness(
        QAccessible.AnnouncementPoliteness.Assertive
        if assertive
        else QAccessible.AnnouncementPoliteness.Polite
    )
    QAccessible.updateAccessibility(event)
