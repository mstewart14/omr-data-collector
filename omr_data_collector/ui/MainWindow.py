from __future__ import annotations

import re
from typing import TYPE_CHECKING

from PySide6.QtCore import QLocale, QSize, Qt
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QStackedWidget,
)

from omr_data_collector import APP_NAME
from omr_data_collector.i18n import (
    language_choices,
    save_language,
    saved_language,
    tr,
)
from omr_data_collector.storage.organization_store import load_organization
from omr_data_collector.ui.AboutDialog import AboutDialog
from omr_data_collector.ui.accessibility import announce
from omr_data_collector.ui.app_font import (
    apply_text_size,
    save_text_size,
    saved_text_size,
)
from omr_data_collector.ui.CapturePage import CapturePage
from omr_data_collector.ui.form_helpers import ask_save_discard_cancel, finish_editing
from omr_data_collector.ui.FormsPage import FormsPage
from omr_data_collector.ui.LanguageDialog import LanguageDialog
from omr_data_collector.ui.OrganizationPage import OrganizationPage
from omr_data_collector.ui.QuestionsPage import QuestionsPage
from omr_data_collector.ui.TableBlocksPage import TableBlocksPage
from omr_data_collector.ui.TextBlocksPage import TextBlocksPage
from omr_data_collector.ui.TextSizeDialog import TextSizeDialog, points

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QWidget

    from omr_data_collector.ui.LibraryPage import LibraryPage

STATUS_MESSAGE_TIMEOUT_MS = 5000
MNEMONIC = re.compile(r"&([^&])")


def choose_language(parent: QWidget, current: str) -> str | None:
    """Ask which language to use; its code ("" for the system's), or None."""
    dialog = LanguageDialog(parent, current)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.chosen_language()


def choose_text_size(parent: QWidget, current: float) -> float | None:
    """Ask how big the app's text should be: points (0 for the desktop's), or None."""
    dialog = TextSizeDialog(parent, current)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.chosen_size()


# Room for the form editor's pages beside its palette and details.
PREFERRED_SIZE = QSize(1400, 900)
# The share of a smaller screen to take instead, leaving the taskbar and edges.
SCREEN_SHARE = 0.9


def _initial_size() -> QSize:
    """PREFERRED_SIZE, or as much of the screen as fits on a smaller one."""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return PREFERRED_SIZE
    available = screen.availableGeometry().size() * SCREEN_SHARE
    return PREFERRED_SIZE.boundedTo(available)


class MainWindow(QMainWindow):
    """The app window: the menu bar, and one section's page filling the rest.

    The menus are how sections are reached, like a document editor's: File is
    the form editor (forms are the documents this app makes); Text, Question and
    Table are the block libraries; Preferences holds the organization's details and the
    language.
    Capture holds the captured sheets. Ctrl+1 to Ctrl+6 open them in that order.

    Every page provides ``status_message``, ``has_unsaved_changes()``, ``save()``
    and ``initial_focus`` (the control that gets focus when the page is opened).
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__()
        self.resize(_initial_size())

        self.forms_page = FormsPage(connection)
        self.text_blocks_page = TextBlocksPage(connection)
        self.questions_page = QuestionsPage(connection)
        self.tables_page = TableBlocksPage(connection)
        self.organization_page = OrganizationPage(connection)
        self.capture_page = CapturePage(connection)
        # In menu order, which is also Ctrl+1 to Ctrl+6.
        self.pages: list[tuple[str, OrganizationPage | LibraryPage | CapturePage]] = [
            (tr("Form editor"), self.forms_page),
            (tr("Text blocks"), self.text_blocks_page),
            (tr("Questions"), self.questions_page),
            (tr("Tables"), self.tables_page),
            (tr("Organization details"), self.organization_page),
            (tr("Captured sheets"), self.capture_page),
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
        self.file_menu, file_actions = self._library_menu(
            menu_bar,
            tr("&File"),
            self.forms_page,
            tr("Form edi&tor"),
            (
                tr("&New form"),
                tr("&Save form"),
                tr("&Revert form"),
                # Within one menu every item needs its own letter: File also has
                # Undo (U) and Redo, so its Duplicate uses L.
                tr("Dup&licate form"),
                tr("&Delete form…"),
            ),
        )
        # Open goes right after New, as in other document editors.
        open_action = QAction(tr("&Open form…"), self.file_menu)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(
            lambda: self._run_in(self.forms_page, self.forms_page.open_from_list)
        )
        after_new = self.file_menu.actions()[
            self.file_menu.actions().index(file_actions[0]) + 1
        ]
        self.file_menu.insertAction(after_new, open_action)
        self.file_menu.addSeparator()
        for text, command in (
            (tr("&Import form…"), self.forms_page.import_form),
            (tr("Export for&m…"), self.forms_page.export_form),
        ):
            action = self.file_menu.addAction(text)
            action.triggered.connect(
                lambda _checked=False, command=command: self._run_in(
                    self.forms_page, command
                )
            )
        self.file_menu.addSeparator()
        for text, command, key in (
            (tr("E&xport as PDF…"), self.forms_page.export_pdf, None),
            (tr("Print pre&view…"), self.forms_page.print_preview, None),
            (
                tr("&Print…"),
                self.forms_page.print_form,
                QKeySequence.StandardKey.Print,
            ),
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
            f"{tr('&Undo form change')}\t{_native(QKeySequence.StandardKey.Undo)}"
        )
        undo_action.triggered.connect(
            lambda: self._run_in(self.forms_page, self.forms_page.undo)
        )
        redo_action = self.file_menu.addAction(
            f"{tr('R&edo form change')}\t{_native(QKeySequence.StandardKey.Redo)}"
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
        quit_action = self.file_menu.addAction(tr("&Quit"))
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)

        self.text_menu, _ = self._library_menu(
            menu_bar,
            tr("&Text"),
            self.text_blocks_page,
            tr("Text block &library"),
            (
                tr("&New text block"),
                tr("&Save text block"),
                tr("&Revert text block"),
                tr("D&uplicate text block"),
                tr("&Delete text block…"),
            ),
        )
        self.question_menu, _ = self._library_menu(
            menu_bar,
            tr("&Question"),
            self.questions_page,
            tr("Question &library"),
            (
                tr("&New question"),
                tr("&Save question"),
                tr("&Revert question"),
                tr("D&uplicate question"),
                tr("&Delete question…"),
            ),
        )
        self.table_menu, _ = self._library_menu(
            menu_bar,
            tr("T&able"),
            self.tables_page,
            tr("Table &library"),
            (
                tr("&New table"),
                tr("&Save table"),
                tr("&Revert table"),
                tr("D&uplicate table"),
                tr("&Delete table…"),
            ),
        )

        self.capture_menu = menu_bar.addMenu(tr("&Capture"))
        self._go_to_action(self.capture_menu, tr("Captured &sheets"), self.capture_page)
        self.capture_menu.addSeparator()
        for text, command in (
            (tr("Add &images…"), self.capture_page.add_images),
            (tr("&Read waiting sheets"), self.capture_page.read_waiting),
            (tr("Read it any&way"), self.capture_page.read_anyway),
            (tr("&Export data…"), self.capture_page.export_data),
        ):
            action = self.capture_menu.addAction(text)
            action.triggered.connect(
                lambda _checked=False, command=command: self._run_in(
                    self.capture_page, command
                )
            )

        self.preferences_menu = menu_bar.addMenu(tr("&Preferences"))
        self._go_to_action(
            self.preferences_menu, tr("&Organization details…"), self.organization_page
        )
        language_action = self.preferences_menu.addAction(tr("&Language…"))
        language_action.triggered.connect(self.change_language)
        text_size_action = self.preferences_menu.addAction(tr("Text &size…"))
        text_size_action.triggered.connect(self.change_text_size)
        self.preferences_menu.addSeparator()
        about_action = self.preferences_menu.addAction(
            tr("&About {app}…").format(app=APP_NAME)
        )
        # On macOS it moves to the application menu, where About belongs.
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self.show_about)

    def _library_menu(
        self,
        menu_bar: QMenuBar,
        title: str,
        page: LibraryPage,
        section_title: str,
        labels: tuple[str, str, str, str, str],
    ) -> tuple[QMenu, list[QAction]]:
        """A library's menu, with its New, Save, Revert, Duplicate and Delete items.

        ``labels`` are those items' text in full, so each is translated whole.
        """
        menu = menu_bar.addMenu(title)
        self._go_to_action(menu, section_title, page)
        menu.addSeparator()
        commands = (
            (page.new_item, None),
            (page.save_from_user, page.save_button),
            (page.revert, page.revert_button),
            (page.duplicate_item, page.duplicate_button),
            (page.delete_item, page.delete_button),
        )
        mirrors: list[tuple[QAction, QWidget]] = []
        actions: list[QAction] = []
        for text, (command, mirrored_button) in zip(labels, commands, strict=True):
            action = menu.addAction(text)
            actions.append(action)
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
        return menu, actions

    def _go_to_action(self, menu: QMenu, text: str, page: QWidget) -> QAction:
        """The item that opens ``page``'s section, showing its Ctrl+number key."""
        index = self._index_of(page)
        key = _section_key(index).toString(QKeySequence.SequenceFormat.NativeText)
        action = menu.addAction(f"{text}\t{key}")
        action.triggered.connect(lambda: self.open_section(index, focus_page=True))
        return action

    def _run_in(self, page: QWidget, command: Callable[[], object]) -> None:
        self.open_section(self._index_of(page), focus_page=True)
        command()

    def _index_of(self, page: QWidget) -> int:
        return next(
            index for index, (_, other) in enumerate(self.pages) if other is page
        )

    def show_about(self) -> None:
        """Preferences > About: the version, and links to the source and issues."""
        AboutDialog(self).exec()

    def change_language(self) -> None:
        """Preferences > Language: choose the language for the next start."""
        current = saved_language()
        chosen = choose_language(self, current)
        if chosen is None or chosen == current:
            return
        save_language(chosen)
        if chosen:
            name = dict(language_choices()).get(chosen, chosen)
            message = tr(
                "The app will be in {language} the next time it starts."
            ).format(language=name)
        else:
            message = tr(
                "The app will follow the system language the next time it starts."
            )
        self.show_status(message)

    def change_text_size(self) -> None:
        """Preferences > Text size: resize the app's text, straight away."""
        current = saved_text_size()
        chosen = choose_text_size(self, current)
        if chosen is None or chosen == current:
            return
        save_text_size(chosen)
        apply_text_size(chosen)
        if chosen:
            message = tr("The app's text is now {size}.").format(size=points(chosen))
        else:
            message = tr("The app's text now follows the desktop's size.")
        self.show_status(message)

    def menu_mnemonics(self) -> set[str]:
        """The menu bar's Alt+letter keys, in the language shown.

        No page may use these letters for its own labels and buttons: a letter
        used twice works for neither. They differ from language to language.
        """
        letters = set()
        for action in self.menuBar().actions():
            match = MNEMONIC.search(action.text().replace("&&", ""))
            if match:
                letters.add(match.group(1).lower())
        return letters

    def show_status(self, message: str) -> None:
        """Show a message in the status bar and have screen readers speak it.

        Screen readers don't watch the status bar, so without the announcement a
        result like "Organization saved." would go unheard.
        """
        self.statusBar().showMessage(message, STATUS_MESSAGE_TIMEOUT_MS)
        announce(self, message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt override)
        # A cell still being typed in counts as a change, and is saved with the rest.
        finish_editing(self)
        unsaved = [
            (index, title, page)
            for index, (title, page) in enumerate(self.pages)
            if page.has_unsaved_changes()
        ]
        if not unsaved:
            event.accept()
            return
        sections = QLocale().createSeparatedList([title for _, title, _ in unsaved])
        answer = ask_save_discard_cancel(
            self,
            tr("Save your unsaved changes ({sections}) before closing?").format(
                sections=sections
            ),
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
