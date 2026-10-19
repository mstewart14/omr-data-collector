"""Building blocks every editing page shares, so each gets the same accessibility."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from omr_data_collector.i18n import tr
from omr_data_collector.ui.accessibility import style_error_label

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from PySide6.QtWidgets import QDialog, QFormLayout


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


def message_box(
    parent: QWidget | None,
    icon: QMessageBox.Icon,
    title: str,
    text: str,
    details: str = "",
) -> QMessageBox:
    """A message box showing ``text`` (and ``details``) as plain text.

    Message boxes otherwise read text that looks like HTML as HTML, links
    included, and the names they show can come from other computers (an
    imported form) or from handwriting.
    """
    box = QMessageBox(icon, title, text, parent=parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    if details:
        box.setInformativeText(details)
    return box


def ask(  # noqa: PLR0913 (a question, its answers, and which are the defaults)
    parent: QWidget | None,
    title: str,
    text: str,
    buttons: Sequence[str | QMessageBox.StandardButton],
    *,
    icon: QMessageBox.Icon = QMessageBox.Icon.Question,
    details: str = "",
    default: int = 0,
    escape: int | None = None,
    destructive: int | None = None,
) -> int | None:
    """Ask a question; the index in ``buttons`` of the answer, None if closed.

    ``buttons`` are labels (with their Alt+letter) or standard buttons such as
    Cancel. ``default`` is the button Enter chooses, ``escape`` the one Escape
    does, and ``destructive`` one that can't be undone, which platforms place
    apart from the others.
    """
    box = message_box(parent, icon, title, text, details)
    added = [
        box.addButton(button)
        if isinstance(button, QMessageBox.StandardButton)
        else box.addButton(
            button,
            QMessageBox.ButtonRole.DestructiveRole
            if index == destructive
            else QMessageBox.ButtonRole.AcceptRole,
        )
        for index, button in enumerate(buttons)
    ]
    box.setDefaultButton(added[default])
    if escape is not None:
        box.setEscapeButton(added[escape])
    box.exec()
    clicked = box.clickedButton()
    return next(
        (index for index, button in enumerate(added) if button is clicked), None
    )


def ask_save_discard_cancel(
    parent: QWidget, question: str
) -> QMessageBox.StandardButton:
    """Ask what to do with unsaved changes; Save is the default answer."""
    answers = (
        QMessageBox.StandardButton.Save,
        QMessageBox.StandardButton.Discard,
        QMessageBox.StandardButton.Cancel,
    )
    chosen = ask(parent, tr("Unsaved changes"), question, answers, escape=2)
    return answers[chosen if chosen is not None else 2]


def ask_new_or_keep_working(
    parent: QWidget, title: str, message: str, new_label: str
) -> bool:
    """After a save, ask whether to start a new item; True to start one.

    ``new_label`` is the button that starts one, like "&New question". Keep
    working is the default (Enter, Escape), so nothing is lost by accident.
    """
    return (
        ask(
            parent,
            title,
            message,
            [new_label, tr("&Keep working")],
            default=1,
            escape=1,
        )
        == 0
    )


class ChangeWhere(Enum):
    """Where a library block's change goes (wiki 50012)."""

    GOING_FORWARD = "going_forward"
    EVERYWHERE = "everywhere"


def ask_where_to_change(
    parent: QWidget, question: str, details: str
) -> ChangeWhere | None:
    """Ask whether a library block's change also goes into the forms using it.

    None if the person cancels. Going forward only is the default (Enter), as it
    leaves every form as it is.
    """
    chosen = ask(
        parent,
        tr("Forms use this"),
        question,
        [
            tr("&Going forward only"),
            tr("Change &everywhere"),
            QMessageBox.StandardButton.Cancel,
        ],
        details=details,
        escape=2,
    )
    if chosen == 0:
        return ChangeWhere.GOING_FORWARD
    if chosen == 1:
        return ChangeWhere.EVERYWHERE
    return None


def confirm_destructive(
    parent: QWidget, title: str, question: str, action: str
) -> bool:
    """Ask before something that can't be undone; True only if ``action`` is chosen.

    Cancel is the default button, so pressing Enter never destroys anything.
    """
    chosen = ask(
        parent,
        title,
        question,
        [action, QMessageBox.StandardButton.Cancel],
        icon=QMessageBox.Icon.Warning,
        default=1,
        escape=1,
        destructive=0,
    )
    return chosen == 0


def ask_save_first(parent: QWidget, question: str) -> bool:
    """Ask to save before going on (printing, say); True to save and go on."""
    chosen = ask(
        parent,
        tr("Save first"),
        question,
        [QMessageBox.StandardButton.Save, QMessageBox.StandardButton.Cancel],
        escape=1,
    )
    return chosen == 0


def confirm_despite_problems(
    parent: QWidget, heading: str, problems: Sequence[str]
) -> bool:
    """List problems and ask whether to go ahead anyway; Cancel is the default."""
    chosen = ask(
        parent,
        tr("Problems to check"),
        heading + "\n\n" + "\n".join(f"- {problem}" for problem in problems),
        [tr("Go ahead anyway"), QMessageBox.StandardButton.Cancel],
        icon=QMessageBox.Icon.Warning,
        default=1,
        escape=1,
    )
    return chosen == 0


def tell(parent: QWidget, title: str, message: str) -> None:
    """Show a message that needs nothing but OK."""
    message_box(parent, QMessageBox.Icon.Information, title, message).exec()


def warn(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    icon: QMessageBox.Icon = QMessageBox.Icon.Warning,
) -> None:
    """Show a problem that needs nothing but OK (a file that couldn't be saved)."""
    message_box(parent, icon, title, message).exec()


def ask_save_path(
    parent: QWidget, title: str, default: Path | str, file_filter: str, suffix: str
) -> Path | None:
    """Ask where to save a file; None if cancelled.

    ``suffix`` (".pdf") is added when the name typed lacks it, after the whole
    name, so a dot in the name ("Intake v1.2") is kept.
    """
    name, _ = QFileDialog.getSaveFileName(parent, title, str(default), file_filter)
    if not name:
        return None
    path = Path(name)
    if path.suffix.casefold() == suffix.casefold():
        return path
    return path.with_name(path.name + suffix)


def ok_cancel_buttons(dialog: QDialog) -> QDialogButtonBox:
    """A dialog's OK and Cancel buttons, accepting and rejecting it."""
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    return buttons


def move_buttons(accessible_name: str) -> tuple[QWidget, QPushButton, QPushButton]:
    """A row of Move up and Move down buttons, named for what they reorder.

    They have no Alt+letter: the list's own up and down keys select, and the
    row's name tells screen readers what the buttons move.
    """
    up = QPushButton(tr("Move up"))
    down = QPushButton(tr("Move down"))
    row = QWidget()
    row.setAccessibleName(accessible_name)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(up)
    layout.addWidget(down)
    layout.addStretch()
    return row, up, down


def save_revert_buttons(
    save_tooltip: str,
) -> tuple[QPushButton, QPushButton, QHBoxLayout]:
    """An editing page's Save (the default) and Revert buttons, at the right."""
    save = QPushButton(tr("&Save"))
    save.setDefault(True)
    save.setToolTip(save_tooltip)
    revert = QPushButton(tr("&Revert"))
    revert.setToolTip(tr("Discard unsaved changes"))
    row = QHBoxLayout()
    row.addStretch()
    row.addWidget(revert)
    row.addWidget(save)
    return save, revert, row


def finish_editing(parent: QWidget) -> None:
    """Put what is being typed in any open table or list cell under ``parent`` into it.

    Call when saving or accepting, before reading what was entered. A cell's
    text only reaches its table when the cell's editor closes, which happens
    when focus moves away; on macOS clicking a button doesn't move focus, and
    neither does a shortcut like Ctrl+S anywhere, so without this the last
    thing typed would be lost. Not for reading on every change: it would close
    an editor as soon as it opened.
    """
    for view in parent.findChildren(QAbstractItemView):
        if view.state() != QAbstractItemView.State.EditingState:
            continue
        for editor in view.viewport().findChildren(QWidget):
            if editor.parent() is view.viewport() and editor.isVisible():
                view.commitData(editor)
                view.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
