from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QFont, QKeySequence, QTextListFormat
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QToolButton, QWidget

from omr_data_collector.ui.form_helpers import add_field_row, add_shortcut
from omr_data_collector.ui.TextBlockEditor import HEADING_LEVELS, TextBlockEditor

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtGui import QShortcut
    from PySide6.QtWidgets import QFormLayout

# Paragraph styles in the Style box: label and heading level (0 = ordinary text).
PARAGRAPH_STYLES = (
    ("Normal text", 0),
    *((f"Heading {level}", level) for level in HEADING_LEVELS),
)
# Shortcuts follow common word processors (Google Docs, LibreOffice).
HEADING_SHORTCUTS = {level: f"Ctrl+Alt+{level}" for level in (0, *HEADING_LEVELS)}
BULLETED_LIST_SHORTCUT = "Ctrl+Shift+8"
NUMBERED_LIST_SHORTCUT = "Ctrl+Shift+7"


class FormattedTextFields:
    """A formatted-text editor with its Style box and formatting buttons.

    Used wherever formatted text is entered (text blocks, question text). Like
    ``AnswerFields`` it isn't a widget: its rows go straight into the page's form,
    so each label stays a sibling of its control for screen readers. The text is
    Markdown; see ``TextBlockEditor``.
    """

    def __init__(  # noqa: PLR0913 (one form row per argument group)
        self,
        form: QFormLayout,
        registry: tuple[dict[str, QWidget], dict[str, QLabel], dict[str, QLabel]],
        *,
        key: str,
        text_label: str,
        style_label: str,
        visible_lines: int,
        shortcut_parent: QWidget,
        on_change: Callable[[], None],
    ) -> None:
        """Add the rows to ``form``.

        Args:
            form: The page's form.
            registry: The page's field widgets, labels and error labels, by key;
                the editor is registered under ``key``.
            key: The validation-error key for the text.
            text_label: The editor's label, with its "&" mnemonic.
            style_label: The Style box's label, with a mnemonic unique on the page.
            visible_lines: The editor's minimum height, in lines of text.
            shortcut_parent: Where the formatting shortcuts work (the page).
            on_change: Called whenever the text changes.
        """
        field_widgets, field_labels, error_labels = registry
        self.style_combo = QComboBox()
        for label, level in PARAGRAPH_STYLES:
            self.style_combo.addItem(label, level)
        self.editor = TextBlockEditor()
        self.editor.setMinimumHeight(
            self.editor.fontMetrics().lineSpacing() * visible_lines
            + 2 * self.editor.frameWidth()
            + int(2 * self.editor.document().documentMargin())
        )

        self.bold_button = _format_button("Bold", "Ctrl+B")
        self.italic_button = _format_button("Italic", "Ctrl+I")
        self.bulleted_button = _format_button("Bulleted list", BULLETED_LIST_SHORTCUT)
        self.numbered_button = _format_button("Numbered list", NUMBERED_LIST_SHORTCUT)
        self._format_buttons = (
            self.bold_button,
            self.italic_button,
            self.bulleted_button,
            self.numbered_button,
        )
        formatting = QWidget()
        formatting.setAccessibleName("Formatting")
        formatting_layout = QHBoxLayout(formatting)
        formatting_layout.setContentsMargins(0, 0, 0, 0)
        for button in self._format_buttons:
            formatting_layout.addWidget(button)
        formatting_layout.addStretch()

        style = QLabel(style_label)
        style.setBuddy(self.style_combo)
        form.addRow(style, self.style_combo)
        form.addRow("Formatting", formatting)
        field_labels[key], error_labels[key] = add_field_row(
            form, text_label, self.editor
        )
        field_widgets[key] = self.editor

        self.editor.textChanged.connect(on_change)
        self.shortcuts = self._connect(shortcut_parent)

    def focus_chain(self) -> list[QWidget]:
        """The controls in tab order."""
        return [self.style_combo, *self._format_buttons, self.editor]

    def markdown(self) -> str:
        return self.editor.markdown()

    def set_markdown(self, text: str) -> None:
        with QSignalBlocker(self.editor):
            self.editor.set_markdown(text)
        self._sync_controls()

    def _connect(self, shortcut_parent: QWidget) -> list[QShortcut]:
        self.editor.cursorPositionChanged.connect(self._sync_controls)
        self.editor.currentCharFormatChanged.connect(self._sync_controls)
        self.style_combo.activated.connect(
            lambda index: self._set_heading_level(self.style_combo.itemData(index))
        )
        self.bold_button.clicked.connect(
            lambda checked: self._format(lambda: self.editor.set_bold(on=checked))
        )
        self.italic_button.clicked.connect(
            lambda checked: self._format(lambda: self.editor.set_italic(on=checked))
        )
        self.bulleted_button.clicked.connect(
            lambda: self._format(
                lambda: self.editor.toggle_list(QTextListFormat.Style.ListDisc)
            )
        )
        self.numbered_button.clicked.connect(
            lambda: self._format(
                lambda: self.editor.toggle_list(QTextListFormat.Style.ListDecimal)
            )
        )
        return [
            add_shortcut(shortcut_parent, "Ctrl+B", self.bold_button.click),
            add_shortcut(shortcut_parent, "Ctrl+I", self.italic_button.click),
            add_shortcut(
                shortcut_parent, BULLETED_LIST_SHORTCUT, self.bulleted_button.click
            ),
            add_shortcut(
                shortcut_parent, NUMBERED_LIST_SHORTCUT, self.numbered_button.click
            ),
            *(
                add_shortcut(
                    shortcut_parent,
                    key,
                    lambda level=level: self._set_heading_level(level),
                )
                for level, key in HEADING_SHORTCUTS.items()
            ),
        ]

    def _format(self, apply: Callable[[], None]) -> None:
        apply()
        self.editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self._sync_controls()

    def _set_heading_level(self, level: int) -> None:
        self._format(lambda: self.editor.set_heading_level(level))

    def _sync_controls(self) -> None:
        """Show the formatting at the cursor, so the checked state is announced."""
        char_format = self.editor.currentCharFormat()
        list_style = self.editor.list_style()
        blockers = [
            QSignalBlocker(control)
            for control in (self.style_combo, *self._format_buttons)
        ]
        self.style_combo.setCurrentIndex(
            self.style_combo.findData(self.editor.heading_level())
        )
        # Heading text is bold by its style, not by the Bold button.
        heading = self.editor.heading_level() > 0
        self.bold_button.setChecked(
            not heading and char_format.fontWeight() >= QFont.Weight.Bold.value
        )
        self.italic_button.setChecked(char_format.fontItalic())
        self.bulleted_button.setChecked(list_style == QTextListFormat.Style.ListDisc)
        self.numbered_button.setChecked(list_style == QTextListFormat.Style.ListDecimal)
        del blockers


def _format_button(text: str, shortcut: str) -> QToolButton:
    button = QToolButton()
    button.setText(text)
    button.setCheckable(True)
    # Reachable with Tab like any other control; QToolButton defaults to
    # mouse-only focus.
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    shortcut_text = QKeySequence(shortcut).toString(
        QKeySequence.SequenceFormat.NativeText
    )
    button.setToolTip(f"{text} ({shortcut_text})")
    button.setAccessibleDescription(f"Shortcut: {shortcut_text}")
    return button
