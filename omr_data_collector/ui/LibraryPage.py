from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QObject, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.i18n import tr
from omr_data_collector.models.naming import copy_name
from omr_data_collector.ui.accessibility import set_field_error, style_error_label
from omr_data_collector.ui.form_helpers import (
    add_field_row,
    add_shortcut,
    ask_save_discard_cancel,
    confirm_destructive,
)

if TYPE_CHECKING:
    from PySide6.QtGui import QShortcut


@dataclass(frozen=True)
class LibraryTexts:
    """Everything a library page says about its items, as whole sentences.

    Whole, so translators can word each one as their language needs (the word
    for "question" may change form, or gender, from sentence to sentence).
    ``{name}`` is an item's name.
    """

    list_label: str  # "Question li&brary"
    name_label: str  # "Na&me (required)"
    new_title: str  # "New question"
    new_status: str  # "New question. Enter a name, ..."
    new_tooltip: str  # "Start a new question (Ctrl+N)"
    duplicate_tooltip: str
    delete_tooltip: str
    save_tooltip: str
    delete_title: str  # "Delete question"
    delete_question: str  # 'Delete the question "{name}"? This can't be undone.'
    saved: str  # 'Question "{name}" saved.'
    deleted: str
    name_taken: str  # 'Another question is already called "{name}".'
    save_first: str  # "Save your changes to this question first?"


class LibraryPage(QWidget):
    """A library of reusable blocks: a list to pick from and an editor for one.

    Handles what every block type shares: New, Duplicate and Delete, the name
    field, Save and Revert, unsaved changes (asked about before leaving them),
    error display and focus, and the shared shortcuts. Subclasses add their own
    fields in ``build_fields`` and say how to read, load, store and copy an item.
    """

    status_message = Signal(str)

    # Off for pages whose items are opened another way (forms, from File > Open).
    SHOW_LIBRARY = True

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__()
        self._connection = connection
        self._items: list[Any] = []
        # The item being edited: a saved one, or None for a new, unsaved one, which
        # already has its permanent ID.
        self._current: Any = None
        self._editing_id = uuid.uuid4().hex
        self._baseline: Any = None
        self.shortcuts: list[QShortcut] = []

        layout = QHBoxLayout(self)
        library_box = self._build_library_box()
        if self.SHOW_LIBRARY:
            layout.addWidget(library_box, stretch=1)
        else:
            # Still there for its list and buttons' state, just not shown.
            library_box.setParent(self)
            library_box.hide()
        layout.addWidget(self.wrap_editor(self._build_editor_box()), stretch=3)
        self._connect_signals()
        self.initial_focus: QWidget = self.item_list

        self._reload_list()
        if self._items:
            self._select(self.item_id(self._items[0]))
            self._edit(self._items[0])
        else:
            self._edit(None)

    # --- What subclasses provide ----------------------------------------------

    def build_fields(self, form: QFormLayout) -> list[QWidget]:
        """Add the item's own fields under the name, and connect their changes.

        Register each field in ``field_widgets``/``field_labels``/
        ``error_labels`` under the key its validation errors use, and connect
        its change signal to ``update_state``.

        Returns:
            The fields' controls in tab order.
        """
        raise NotImplementedError

    def load_fields(self, item: Any) -> None:  # noqa: ANN401
        """Show ``item`` (None for a new item) in the subclass's fields."""
        raise NotImplementedError

    def read_item(self, name: str, item_id: str) -> Any:  # noqa: ANN401
        """The item as currently entered, normalized."""
        raise NotImplementedError

    def list_items(self) -> list[Any]:
        raise NotImplementedError

    def wrap_editor(self, editor_box: QWidget) -> QWidget:
        """Put more around the editor (the form pages); the editor alone by default."""
        return editor_box

    def store_item(self, item: Any) -> None:  # noqa: ANN401
        raise NotImplementedError

    def remove_item(self, item_id: str) -> None:
        raise NotImplementedError

    def copy_item(self, item: Any, name: str) -> Any:  # noqa: ANN401
        """A new item (with a new ID) like ``item`` but called ``name``."""
        raise NotImplementedError

    def item_id(self, item: Any) -> str:  # noqa: ANN401
        raise NotImplementedError

    def texts(self) -> LibraryTexts:
        """The page's labels and messages, in the person's language."""
        raise NotImplementedError

    def delete_question(self, item: Any) -> str:  # noqa: ANN401
        """What to ask before deleting ``item``."""
        return self.texts().delete_question.format(name=item.name)

    def saved_message(self, item: Any) -> str:  # noqa: ANN401
        """The status message after ``item`` is saved."""
        return self.texts().saved.format(name=item.name)

    # --- Public actions -------------------------------------------------------

    def has_unsaved_changes(self) -> bool:
        return self._entered() != self._baseline

    def save(self) -> bool:
        """Save what is entered; False, with the errors shown, if it can't be.

        Used wherever saving is a step in something else (switching items,
        closing the window); the Save button and Ctrl+S use ``save_from_user``.
        """
        item = self._entered()
        other_names = {
            other.name
            for other in self._items
            if self.item_id(other) != self._editing_id
        }
        errors = item.validation_errors(other_names)
        if not errors:
            try:
                self.store_item(item)
            except sqlite3.IntegrityError:
                # Another window or process took the name since the list loaded.
                errors = {"name": self.texts().name_taken.format(name=item.name)}
        self.show_errors(errors)
        if errors:
            first_invalid = next(key for key in self.field_widgets if key in errors)
            self.field_widgets[first_invalid].setFocus(Qt.FocusReason.OtherFocusReason)
            count = len(errors)
            self.status_message.emit(
                tr("%n field(s) to fix before saving.", None, count)
            )
            return False

        self._reload_list()
        self._select(self.item_id(item))
        # As stored, which may differ from what was entered (a form's new version).
        stored = next(
            (
                other
                for other in self._items
                if self.item_id(other) == self.item_id(item)
            ),
            item,
        )
        self._edit(stored)
        self.status_message.emit(self.saved_message(stored))
        return True

    def open_item(self, item_id: str) -> bool:
        """Open a saved item, asking about unsaved changes first; False if not."""
        if item_id == self._editing_id and self._current is not None:
            return True
        item = next(
            (other for other in self._items if self.item_id(other) == item_id), None
        )
        if item is None or not self._resolve_unsaved_changes():
            return False
        self._select(item_id)
        self._edit(item)
        return True

    def items(self) -> list[Any]:
        """The saved items, as last listed."""
        return list(self._items)

    def save_from_user(self) -> None:
        """Save because the person asked to (Save, Ctrl+S, Enter, the menu)."""
        if self.save():
            self.after_user_save(self._current)

    def after_user_save(self, item: Any) -> None:  # noqa: ANN401
        """What to do next after the person saves ``item``; nothing by default."""

    def revert(self) -> None:
        self._edit(self._current)

    def new_item(self) -> None:
        if not self._resolve_unsaved_changes():
            return
        self._select(None)
        self._edit(None)
        self.name_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self.status_message.emit(self.texts().new_status)

    def duplicate_item(self) -> None:
        if self._current is None or not self._resolve_unsaved_changes():
            return
        original = self._current
        duplicate = self.copy_item(
            original, copy_name(original.name, {item.name for item in self._items})
        )
        self.store_item(duplicate)
        self._reload_list()
        self._select(self.item_id(duplicate))
        self._edit(duplicate)
        self.name_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self.name_edit.selectAll()
        self.status_message.emit(
            tr('Duplicated "{original}" as "{copy}".').format(
                original=original.name, copy=duplicate.name
            )
        )

    def delete_item(self) -> None:
        if self._current is None:
            return
        doomed = self._current
        if not confirm_destructive(
            self, self.texts().delete_title, self.delete_question(doomed), tr("Delete")
        ):
            return
        row = self.item_list.currentRow()
        self.remove_item(self.item_id(doomed))
        self._reload_list()
        if self._items:
            neighbour = self._items[min(row, len(self._items) - 1)]
            self._select(self.item_id(neighbour))
            self._edit(neighbour)
            self.item_list.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self._select(None)
            self._edit(None)
        self.status_message.emit(self.texts().deleted.format(name=doomed.name))

    def show_errors(self, errors: dict[str, str]) -> None:
        for key, label in self.error_labels.items():
            set_field_error(
                self.form, self.field_widgets[key], label, errors.get(key, "")
            )

    def update_state(self) -> None:
        unsaved = self.has_unsaved_changes()
        self.save_button.setEnabled(unsaved)
        self.revert_button.setEnabled(unsaved)
        saved = self._current is not None
        self.duplicate_button.setEnabled(saved)
        self.delete_button.setEnabled(saved)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt override)
        # A theme switch changes the background, so the error color is chosen again
        # to keep its contrast.
        if event.type() == QEvent.Type.PaletteChange:
            for label in self.error_labels.values():
                style_error_label(label, self.palette())
        super().changeEvent(event)

    # --- Layout -----------------------------------------------------------------

    def _build_library_box(self) -> QGroupBox:
        self.item_list = QListWidget()
        texts = self.texts()
        list_label = QLabel(texts.list_label)
        list_label.setBuddy(self.item_list)
        self.new_button = QPushButton(tr("&New"))
        self.new_button.setToolTip(texts.new_tooltip)
        self.duplicate_button = QPushButton(tr("D&uplicate"))
        self.duplicate_button.setToolTip(texts.duplicate_tooltip)
        self.delete_button = QPushButton(tr("&Delete"))
        self.delete_button.setToolTip(texts.delete_tooltip)
        buttons = QHBoxLayout()
        for button in (self.new_button, self.duplicate_button, self.delete_button):
            buttons.addWidget(button)

        box = QGroupBox(tr("Library"))
        box_layout = QVBoxLayout(box)
        box_layout.addWidget(list_label)
        box_layout.addWidget(self.item_list)
        box_layout.addLayout(buttons)
        return box

    def _build_editor_box(self) -> QGroupBox:
        self.form = QFormLayout()
        self.name_edit = QLineEdit()
        name_label, name_error = add_field_row(
            self.form, self.texts().name_label, self.name_edit
        )
        self.field_widgets: dict[str, QWidget] = {"name": self.name_edit}
        self.field_labels: dict[str, QLabel] = {"name": name_label}
        self.error_labels: dict[str, QLabel] = {"name": name_error}
        self._field_focus_chain = self.build_fields(self.form)
        # Takes up spare height when no field can grow (a written answer, say);
        # otherwise the form spreads its rows apart. Growing fields (the text
        # editor, the choices table) share the space with it.
        self.form.addItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        )

        self.save_button = QPushButton(tr("&Save"))
        self.save_button.setDefault(True)
        self.save_button.setToolTip(self.texts().save_tooltip)
        self.revert_button = QPushButton(tr("&Revert"))
        self.revert_button.setToolTip(tr("Discard unsaved changes"))
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.revert_button)
        buttons.addWidget(self.save_button)

        # The form scrolls, so nothing is cut off in a small window or at a large
        # system font size; Save and Revert stay in view below it.
        form_container = QWidget()
        form_container.setLayout(self.form)
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Not a Tab stop of its own: focus goes to the fields inside it.
        self.form_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.form_scroll.setWidget(form_container)
        # It scrolls up and down only, and is never narrower than its fields at
        # the font size in use: a sideways scroll would leave the start of every
        # label and field out of view (as at a large desktop font size).
        self.form_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        form_container.installEventFilter(self)
        self._fit_form_width()
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.focusChanged.connect(self._scroll_to_focus)

        self.editor_box = QGroupBox()
        box_layout = QVBoxLayout(self.editor_box)
        box_layout.addWidget(self.form_scroll)
        box_layout.addLayout(buttons)
        return self.editor_box

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt override)
        # Fields shown or hidden, or a new font size, change the width needed.
        if watched is self.form_scroll.widget() and event.type() in {
            QEvent.Type.LayoutRequest,
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
        }:
            self._fit_form_width()
        return super().eventFilter(watched, event)

    def _fit_form_width(self) -> None:
        """Keep the form's scroll area at least as wide as the form needs."""
        form = self.form_scroll.widget()
        if form is None:
            return
        scroll_bar = self.form_scroll.verticalScrollBar().sizeHint().width()
        self.form_scroll.setMinimumWidth(
            form.minimumSizeHint().width()
            + scroll_bar
            + 2 * self.form_scroll.frameWidth()
        )

    def _scroll_to_focus(self, _old: QWidget | None, new: QWidget | None) -> None:
        # A scroll area doesn't follow keyboard focus by itself; without this,
        # tabbing to a field below the fold would leave it out of sight.
        form = self.form_scroll.widget()
        if new is not None and form is not None and form.isAncestorOf(new):
            self.form_scroll.ensureWidgetVisible(new)

    def _connect_signals(self) -> None:
        self.save_button.clicked.connect(self.save_from_user)
        self.revert_button.clicked.connect(self.revert)
        self.new_button.clicked.connect(self.new_item)
        self.duplicate_button.clicked.connect(self.duplicate_item)
        self.delete_button.clicked.connect(self.delete_item)
        self.item_list.currentItemChanged.connect(self._on_selection_changed)
        self.name_edit.textChanged.connect(self.update_state)
        self.name_edit.returnPressed.connect(self.save_from_user)

        self.shortcuts += [
            add_shortcut(self, QKeySequence.StandardKey.Save, self.save_from_user),
            add_shortcut(self, QKeySequence.StandardKey.New, self.new_item),
        ]
        delete_shortcut = add_shortcut(
            self.item_list, QKeySequence.StandardKey.Delete, self.delete_item
        )
        # Only from the list: in the editor, Delete deletes text.
        delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.shortcuts.append(delete_shortcut)

        # Tab follows the screen: the library, then the editor top to bottom.
        focus_chain = [
            self.item_list,
            self.new_button,
            self.duplicate_button,
            self.delete_button,
            self.name_edit,
            *self._field_focus_chain,
            self.revert_button,
            self.save_button,
        ]
        for before, after in pairwise(focus_chain):
            QWidget.setTabOrder(before, after)

    # --- State --------------------------------------------------------------------

    def _entered(self) -> Any:  # noqa: ANN401
        return self.read_item(self.name_edit.text(), self._editing_id)

    def _reload_list(self) -> None:
        self._items = self.list_items()
        with QSignalBlocker(self.item_list):
            self.item_list.clear()
            for item in self._items:
                list_item = QListWidgetItem(item.name)
                list_item.setData(Qt.ItemDataRole.UserRole, self.item_id(item))
                self.item_list.addItem(list_item)

    def _select(self, item_id: str | None) -> None:
        """Select an item in the list without treating it as the person's choice."""
        with QSignalBlocker(self.item_list):
            self.item_list.setCurrentRow(-1)
            for row in range(self.item_list.count()):
                if self.item_list.item(row).data(Qt.ItemDataRole.UserRole) == item_id:
                    self.item_list.setCurrentRow(row)
                    break

    def _edit(self, item: Any) -> None:  # noqa: ANN401
        """Load a saved item, or a blank new one, into the editor."""
        self._current = item
        self._editing_id = self.item_id(item) if item is not None else uuid.uuid4().hex
        self.show_errors({})
        with QSignalBlocker(self.name_edit):
            self.name_edit.setText(item.name if item is not None else "")
        self.load_fields(item)
        # Compared with what the fields now read back, not the stored item, so a
        # widget's own formatting of the same content never counts as a change.
        self._baseline = self._entered()
        self.editor_box.setTitle(
            tr('Editing "{name}"').format(name=item.name)
            if item is not None
            else self.texts().new_title
        )
        self.update_state()

    def _on_selection_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        if current is None:
            return
        # Read now: saving below reloads the list, which deletes this list item.
        item_id = current.data(Qt.ItemDataRole.UserRole)
        if not self._resolve_unsaved_changes():
            # Cancelled: put the selection back on the item still being edited.
            self._select(self.item_id(self._current) if self._current else None)
            return
        self._select(item_id)
        self._edit(next(item for item in self._items if self.item_id(item) == item_id))

    def _resolve_unsaved_changes(self) -> bool:
        """Ask about unsaved changes before leaving them; False means stay."""
        if not self.has_unsaved_changes():
            return True
        answer = ask_save_discard_cancel(self, self.texts().save_first)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard
