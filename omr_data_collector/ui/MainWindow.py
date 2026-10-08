from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QMenu, QMenuBar, QMessageBox, QStackedWidget

from omr_data_collector import APP_NAME
from omr_data_collector.storage.organization_store import load_organization
from omr_data_collector.ui.accessibility import announce
from omr_data_collector.ui.form_helpers import ask_save_discard_cancel
from omr_data_collector.ui.FormsPage import FormsPage
from omr_data_collector.ui.OrganizationPage import OrganizationPage
from omr_data_collector.ui.QuestionsPage import QuestionsPage
from omr_data_collector.ui.TableBlocksPage import TableBlocksPage
from omr_data_collector.ui.TextBlocksPage import TextBlocksPage

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QWidget

    from omr_data_collector.ui.LibraryPage import LibraryPage

STATUS_MESSAGE_TIMEOUT_MS = 5000
# The menu bar's Alt+letter keys. No page may use these letters for its own
# labels and buttons: a letter used twice works for neither.
MENU_MNEMONICS = frozenset("ftqap")


class MainWindow(QMainWindow):
    """The app window: the menu bar, and one section's page filling the rest.

    The menus are how sections are reached, like a document editor's: File is
    the form editor (forms are the documents this app makes); Text, Question and
    Table are the block libraries; Preferences holds the organization's details.
    Ctrl+1 to Ctrl+5 open them in that order.

    Every page provides ``status_message``, ``has_unsaved_changes()``, ``save()``
    and ``initial_focus`` (the control that gets focus when the page is opened).
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__()
        # Room for the form editor's pages beside its palette and details.
        self.resize(1400, 900)

        self.forms_page = FormsPage(connection)
        self.text_blocks_page = TextBlocksPage(connection)
        self.questions_page = QuestionsPage(connection)
        self.tables_page = TableBlocksPage(connection)
        self.organization_page = OrganizationPage(connection)
        # In menu order, which is also Ctrl+1 to Ctrl+5.
        self.pages: list[tuple[str, OrganizationPage | LibraryPage]] = [
            ("Form editor", self.forms_page),
            ("Text blocks", self.text_blocks_page),
            ("Questions", self.questions_page),
            ("Tables", self.tables_page),
            ("Organization details", self.organization_page),
        ]

        self.stack = QStackedWidget()
        self.section_shortcuts: list[QShortcut] = []
        for index, (_, page) in enumerate(self.pages):
            self.stack.addWidget(page)
            page.status_message.connect(self.show_status)
            shortcut = QShortcut(_section_key(index), self)
            shortcut.activated.connect(
                lambda index=index: self.open_section(index, focus_page=True)
            )
            self.section_shortcuts.append(shortcut)
        self.setCentralWidget(self.stack)
        self._build_menus()
        self.forms_page.organization_needed.connect(
            lambda: self.open_section(
                self._index_of(self.organization_page), focus_page=True
            )
        )

        # The form editor is the main work; before the organization is entered,
        # that comes first, since every form's header shows it.
        first = (
            self.forms_page
            if load_organization(connection) is not None
            else self.organization_page
        )
        self.open_section(self._index_of(first))

    def open_section(self, index: int, *, focus_page: bool = False) -> None:
        """Show a section's page, which keeps any unsaved changes while hidden.

        From a menu or shortcut, focus moves into the page so its first control
        is announced.
        """
        title, page = self.pages[index]
        self.stack.setCurrentWidget(page)
        # The title names the section, so it's announced with the window and
        # shown in the task bar.
        self.setWindowTitle(f"{title} - {APP_NAME}")
        if focus_page:
            page.initial_focus.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _build_menus(self) -> None:
        """A menu per kind of document, like a word processor's menu bar.

        Each command opens its section and acts there, so the result is always
        in view. Shortcuts that belong to a section (Ctrl+N, Ctrl+Z…) are shown
        after a tab in the item's text, which Qt displays without binding them,
        so the section's own keys keep working.
        """
        menu_bar = self.menuBar()
        self.file_menu = self._library_menu(
            menu_bar, "&File", "form", self.forms_page, "Form edi&tor"
        )
        # Within one menu every item needs its own letter: File also has Undo
        # (U) and Redo, so its Duplicate uses L.
        duplicate = next(
            action
            for action in self.file_menu.actions()
            if action.text() == "D&uplicate form"
        )
        duplicate.setText("Dup&licate form")
        # Open goes right after New, as in other document editors.
        open_action = QAction("&Open form…", self.file_menu)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(
            lambda: self._run_in(self.forms_page, self.forms_page.open_from_list)
        )
        new_form = next(
            action
            for action in self.file_menu.actions()
            if action.text() == "&New form"
        )
        after_new = self.file_menu.actions()[
            self.file_menu.actions().index(new_form) + 1
        ]
        self.file_menu.insertAction(after_new, open_action)
        self.file_menu.addSeparator()
        for text, command, key in (
            ("E&xport as PDF…", self.forms_page.export_pdf, None),
            ("Print pre&view…", self.forms_page.print_preview, None),
            ("&Print…", self.forms_page.print_form, QKeySequence.StandardKey.Print),
        ):
            action = self.file_menu.addAction(text)
            if key is not None:
                action.setShortcut(key)
            action.triggered.connect(
                lambda _checked=False, command=command: self._run_in(
                    self.forms_page, command
                )
            )
        self.file_menu.addSeparator()
        undo_action = self.file_menu.addAction(
            f"&Undo form change\t{_native(QKeySequence.StandardKey.Undo)}"
        )
        undo_action.triggered.connect(
            lambda: self._run_in(self.forms_page, self.forms_page.undo)
        )
        redo_action = self.file_menu.addAction(
            f"R&edo form change\t{_native(QKeySequence.StandardKey.Redo)}"
        )
        redo_action.triggered.connect(
            lambda: self._run_in(self.forms_page, self.forms_page.redo)
        )
        self.file_menu.aboutToShow.connect(
            lambda: (
                undo_action.setEnabled(self.forms_page.can_undo()),
                redo_action.setEnabled(self.forms_page.can_redo()),
            )
        )
        self.file_menu.addSeparator()
        quit_action = self.file_menu.addAction("&Quit")
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)

        self.text_menu = self._library_menu(
            menu_bar,
            "&Text",
            "text block",
            self.text_blocks_page,
            "Text block &library",
        )
        self.question_menu = self._library_menu(
            menu_bar, "&Question", "question", self.questions_page, "Question &library"
        )
        self.table_menu = self._library_menu(
            menu_bar, "T&able", "table", self.tables_page, "Table &library"
        )

        self.preferences_menu = menu_bar.addMenu("&Preferences")
        self._go_to_action(
            self.preferences_menu, "&Organization details…", self.organization_page
        )

    def _library_menu(
        self,
        menu_bar: QMenuBar,
        title: str,
        noun: str,
        page: LibraryPage,
        section_title: str,
    ) -> QMenu:
        menu = menu_bar.addMenu(title)
        self._go_to_action(menu, section_title, page)
        menu.addSeparator()
        commands = (
            (f"&New {noun}", page.new_item, None),
            (f"&Save {noun}", page.save_from_user, page.save_button),
            (f"&Revert {noun}", page.revert, page.revert_button),
            (f"D&uplicate {noun}", page.duplicate_item, page.duplicate_button),
            (f"&Delete {noun}…", page.delete_item, page.delete_button),
        )
        mirrors: list[tuple[QAction, QWidget]] = []
        for text, command, mirrored_button in commands:
            action = menu.addAction(text)
            action.triggered.connect(
                lambda _checked=False, command=command: self._run_in(page, command)
            )
            if mirrored_button is not None:
                mirrors.append((action, mirrored_button))

        def sync() -> None:
            # Available exactly when the page's own button is.
            for action, button in mirrors:
                action.setEnabled(button.isEnabled())

        menu.aboutToShow.connect(sync)
        return menu

    def _go_to_action(self, menu: QMenu, text: str, page: QWidget) -> QAction:
        """The item that opens ``page``'s section, showing its Ctrl+number key."""
        index = self._index_of(page)
        key = _section_key(index).toString(QKeySequence.SequenceFormat.NativeText)
        action = menu.addAction(f"{text}\t{key}")
        action.triggered.connect(lambda: self.open_section(index, focus_page=True))
        return action

    def _run_in(self, page: LibraryPage, command: Callable[[], object]) -> None:
        self.open_section(self._index_of(page), focus_page=True)
        command()

    def _index_of(self, page: QWidget) -> int:
        return next(
            index for index, (_, other) in enumerate(self.pages) if other is page
        )

    def show_status(self, message: str) -> None:
        """Show a message in the status bar and have screen readers speak it.

        Screen readers don't watch the status bar, so without the announcement a
        result like "Organization saved." would go unheard.
        """
        self.statusBar().showMessage(message, STATUS_MESSAGE_TIMEOUT_MS)
        announce(self, message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt override)
        unsaved = [
            (index, title, page)
            for index, (title, page) in enumerate(self.pages)
            if page.has_unsaved_changes()
        ]
        if not unsaved:
            event.accept()
            return
        sections = ", ".join(title for _, title, _ in unsaved)
        answer = ask_save_discard_cancel(
            self, f"Save your unsaved changes ({sections}) before closing?"
        )
        if answer == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return
        if answer == QMessageBox.StandardButton.Save:
            for _, _, page in unsaved:
                page.save()
            # Saving fails, leaving the changes, when a field is invalid; stay open
            # on that page so the errors can be fixed.
            still_unsaved = [
                index for index, _, page in unsaved if page.has_unsaved_changes()
            ]
            if still_unsaved:
                self.open_section(still_unsaved[0])
                event.ignore()
                return
        event.accept()


def _section_key(index: int) -> QKeySequence:
    return QKeySequence(f"Ctrl+{index + 1}")


def _native(key: QKeySequence.StandardKey) -> str:
    """A standard shortcut as this platform writes it ("Ctrl+Z", "⌘Z")."""
    return QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)
