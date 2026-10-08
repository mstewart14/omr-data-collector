"""Building blocks every editing page shares, so each gets the same accessibility."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLabel, QMessageBox

from omr_data_collector.ui.accessibility import style_error_label

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

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


def add_standard_shortcuts(
    parent: QWidget,
    key: QKeySequence.StandardKey,
    callback: Callable[[], object],
    *extra: str,
) -> list[QShortcut]:
    """Shortcuts for every key the platform binds to ``key``, plus ``extra`` keys.

    ``QShortcut(QKeySequence(StandardKey.Redo))`` only listens for the first
    binding (Ctrl+Shift+Z on Linux), so a second one like Ctrl+Y would be ignored.
    """
    sequences = list(QKeySequence.keyBindings(key))
    for text in extra:
        sequence = QKeySequence(text)
        if sequence not in sequences:
            sequences.append(sequence)
    return [add_shortcut(parent, sequence, callback) for sequence in sequences]


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


def ask_new_or_keep_working(parent: QWidget, noun: str, name: str) -> bool:
    """After a save, ask whether to start a new item; True to start one.

    Keep working is the default (Enter, Escape), so nothing is lost by accident.
    """
    box = QMessageBox(
        QMessageBox.Icon.Question,
        f"{noun.capitalize()} saved",
        f'{noun.capitalize()} "{name}" saved. Start a new {noun}, or keep working on '
        "this one?",
        parent=parent,
    )
    new_button = box.addButton(f"&New {noun}", QMessageBox.ButtonRole.AcceptRole)
    keep_button = box.addButton("&Keep working", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(keep_button)
    box.setEscapeButton(keep_button)
    box.exec()
    return box.clickedButton() is new_button


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


def ask_save_first(parent: QWidget, question: str) -> bool:
    """Ask to save before going on (printing, say); True to save and go on."""
    box = QMessageBox(QMessageBox.Icon.Question, "Save first", question, parent=parent)
    save_button = box.addButton(QMessageBox.StandardButton.Save)
    cancel_button = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(save_button)
    box.setEscapeButton(cancel_button)
    box.exec()
    return box.clickedButton() is save_button


def confirm_despite_problems(
    parent: QWidget, heading: str, problems: Sequence[str]
) -> bool:
    """List problems and ask whether to go ahead anyway; Cancel is the default."""
    box = QMessageBox(
        QMessageBox.Icon.Warning,
        "Problems to check",
        heading + "\n\n" + "\n".join(f"- {problem}" for problem in problems),
        parent=parent,
    )
    go_ahead = box.addButton("Go ahead anyway", QMessageBox.ButtonRole.AcceptRole)
    cancel_button = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel_button)
    box.setEscapeButton(cancel_button)
    box.exec()
    return box.clickedButton() is go_ahead


def tell(parent: QWidget, title: str, message: str) -> None:
    """Show a message that needs nothing but OK."""
    box = QMessageBox(QMessageBox.Icon.Information, title, message, parent=parent)
    box.exec()
