"""Building blocks every editing page shares, so each gets the same accessibility."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLabel, QMessageBox

from omr_data_collector.ui.accessibility import style_error_label

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QFormLayout, QWidget


def add_field_row(
    form: QFormLayout, label_text: str, field: QWidget
) -> tuple[QLabel, QLabel]:
    """Add a labelled field and, under it, its hidden error row.

    The label and field are siblings in ``form``: that is how Qt tells screen
    readers which label names the field, and the label's buddy is what its
    Alt+letter mnemonic (the letter after "&" in ``label_text``) focuses.

    Returns:
        The label, and the error label to pass to ``set_field_error``.
    """
    label = QLabel(label_text)
    label.setBuddy(field)
    form.addRow(label, field)
    error_label = QLabel()
    style_error_label(error_label, field.palette())
    form.addRow("", error_label)
    form.setRowVisible(error_label, False)  # noqa: FBT003 (Qt API is positional)
    return label, error_label


def add_shortcut(
    parent: QWidget,
    key: QKeySequence | QKeySequence.StandardKey | str,
    callback: Callable[[], object],
) -> QShortcut:
    """A keyboard shortcut that works while focus is anywhere inside ``parent``."""
    shortcut = QShortcut(QKeySequence(key), parent)
    shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    shortcut.activated.connect(callback)
    return shortcut


def ask_save_discard_cancel(
    parent: QWidget, question: str
) -> QMessageBox.StandardButton:
    """Ask what to do with unsaved changes; Save is the default answer."""
    return QMessageBox.question(
        parent,
        "Unsaved changes",
        question,
        QMessageBox.StandardButton.Save
        | QMessageBox.StandardButton.Discard
        | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Save,
    )


def confirm_destructive(
    parent: QWidget, title: str, question: str, action: str
) -> bool:
    """Ask before something that can't be undone; True only if ``action`` is chosen.

    Cancel is the default button, so pressing Enter never destroys anything.
    """
    box = QMessageBox(QMessageBox.Icon.Warning, title, question, parent=parent)
    action_button = box.addButton(action, QMessageBox.ButtonRole.DestructiveRole)
    cancel_button = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel_button)
    box.setEscapeButton(cancel_button)
    box.exec()
    return box.clickedButton() is action_button
