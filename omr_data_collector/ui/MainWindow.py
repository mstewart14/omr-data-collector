from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from omr_data_collector import APP_NAME
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

    from omr_data_collector.ui.LibraryPage import LibraryPage

STATUS_MESSAGE_TIMEOUT_MS = 5000
# The menu bar's Alt+letter keys. No page may use these letters for its own
# labels and buttons: a letter used twice works for neither.
MENU_MNEMONICS = frozenset("ftqa")
# Room beside the longest section name, so it never truncates at larger fonts.
SECTIONS_PADDING = 32


class MainWindow(QMainWindow):
    """The app window: a list of sections on the left, the chosen section's page.

    Every page provides ``status_message``, ``has_unsaved_changes()``, ``save()``
    and ``initial_focus`` (the control that gets focus when the page is opened).
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__()
        # Room for the form editor's pages beside its palette and details.
        self.resize(1400, 900)

        self.organization_page = OrganizationPage(connection)
        self.text_blocks_page = TextBlocksPage(connection)
        self.questions_page = QuestionsPage(connection)
        self.tables_page = TableBlocksPage(connection)
        self.forms_page = FormsPage(connection)
        self.pages: list[tuple[str, OrganizationPage | LibraryPage]] = [
            ("Organization", self.organization_page),
            ("Text blocks", self.text_blocks_page),
            ("Questions", self.questions_page),
            ("Tables", self.tables_page),
            ("Forms", self.forms_page),
        ]

        self.sections = QListWidget()
        self.sections.setAccessibleName("Sections")
        self.stack = QStackedWidget()
        self.section_shortcuts: list[QShortcut] = []
        for index, (title, page) in enumerate(self.pages):
            key = QKeySequence(f"Ctrl+{index + 1}")
            self.sections.addItem(title)
            self.sections.item(index).setToolTip(
                f"{title} ({key.toString(QKeySequence.SequenceFormat.NativeText)})"
            )
            self.stack.addWidget(page)
            page.status_message.connect(self.show_status)
            shortcut = QShortcut(key, self)
            shortcut.activated.connect(
                lambda index=index: self.open_section(index, focus_page=True)
            )
            self.section_shortcuts.append(shortcut)
        self.sections.setFixedWidth(
            self.sections.sizeHintForColumn(0) + SECTIONS_PADDING
        )
        self.sections.currentRowChanged.connect(self.open_section)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(self.sections)
        layout.addWidget(self.stack, stretch=1)
        self.setCentralWidget(central)
        self._build_menus()
        self.open_section(0)

    def open_section(self, index: int, *, focus_page: bool = False) -> None:
        """Show a section's page, which keeps any unsaved changes while hidden.

        Opened by keyboard shortcut, focus moves into the page so its first
        control is announced; picked in the list, focus stays in the list so the
        arrow keys keep moving through the sections.
        """
        title, page = self.pages[index]
        if self.sections.currentRow() != index:
            self.sections.setCurrentRow(index)
        self.stack.setCurrentWidget(page)
        # The title names the section, so it's announced with the window and
        # shown in the task bar.
        self.setWindowTitle(f"{title} - {APP_NAME}")
        if focus_page:
            page.initial_focus.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _build_menus(self) -> None:
        """A menu per kind of document, like a word processor's menu bar.

        File holds the forms, as the documents this app makes; Text, Question
        and Table hold the reusable blocks. Each command opens its section and
        acts there, so the result is always in view.
        """
        menu_bar = self.menuBar()
        self.file_menu = self._library_menu(menu_bar, "&File", "form", self.forms_page)
        # Open goes right after New, as in other document editors.
        open_action = QAction("&Open form…", self.file_menu)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(
            lambda: self._run_in(self.forms_page, self.forms_page.open_from_list)
        )
        self.file_menu.insertAction(self.file_menu.actions()[1], open_action)
        self.file_menu.addSeparator()
        organization = self.file_menu.addAction("&Organization details…")
        organization.triggered.connect(
            lambda: self.open_section(
                self._index_of(self.organization_page), focus_page=True
            )
        )
        self.file_menu.addSeparator()
        quit_action = self.file_menu.addAction("&Quit")
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        self.text_menu = self._library_menu(
            menu_bar, "&Text", "text block", self.text_blocks_page
        )
        self.question_menu = self._library_menu(
            menu_bar, "&Question", "question", self.questions_page
        )
        self.table_menu = self._library_menu(
            menu_bar, "T&able", "table", self.tables_page
        )

    def _library_menu(
        self, menu_bar: QMenuBar, title: str, noun: str, page: LibraryPage
    ) -> QMenu:
        menu = menu_bar.addMenu(title)
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
