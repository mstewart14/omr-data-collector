from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt
from PySide6.QtGui import QFont, QKeySequence, QPalette, QTextListFormat
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QToolButton, QWidget

from omr_data_collector.i18n import tr
from omr_data_collector.ui.form_helpers import add_field_row, add_shortcut
from omr_data_collector.ui.format_icons import format_icon
from omr_data_collector.ui.TextBlockEditor import HEADING_LEVELS, TextBlockEditor

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtGui import QShortcut
    from PySide6.QtWidgets import QFormLayout


def paragraph_styles() -> tuple[tuple[str, int], ...]:
    """The Style box's choices: label and heading level (0 = ordinary text)."""
    return (
        (tr("Normal text"), 0),
        *(
            (tr("Heading {level}").format(level=level), level)
            for level in HEADING_LEVELS
        ),
    )


# Shortcuts follow common word processors (Google Docs, LibreOffice).
HEADING_SHORTCUTS = {level: f"Ctrl+Alt+{level}" for level in (0, *HEADING_LEVELS)}
BULLETED_LIST_SHORTCUT = "Ctrl+Shift+8"
NUMBERED_LIST_SHORTCUT = "Ctrl+Shift+7"
MIN_ICON_PX = 16
ICON_EXTRA_PX = 2


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
        grow: bool = True,
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
            grow: Whether the editor takes spare height; when not, it stays
                at ``visible_lines`` and scrolls.
            shortcut_parent: Where the formatting shortcuts work (the page).
            on_change: Called whenever the text changes.
        """
        field_widgets, field_labels, error_labels = registry
        self.style_combo = QComboBox()
        for label, level in paragraph_styles():
            self.style_combo.addItem(label, level)
        self.editor = TextBlockEditor()
        height = (
            self.editor.fontMetrics().lineSpacing() * visible_lines
            + 2 * self.editor.frameWidth()
            + int(2 * self.editor.document().documentMargin())
        )
        self.editor.setMinimumHeight(height)
        if not grow:
            self.editor.setMaximumHeight(height)

        self.bold_button = FormatButton(tr("Bold"), "bold", "Ctrl+B")
        self.italic_button = FormatButton(tr("Italic"), "italic", "Ctrl+I")
        self.bulleted_button = FormatButton(
            tr("Bulleted list"), "bulleted_list", BULLETED_LIST_SHORTCUT
        )
        self.numbered_button = FormatButton(
            tr("Numbered list"), "numbered_list", NUMBERED_LIST_SHORTCUT
        )
        self._format_buttons = (
            self.bold_button,
            self.italic_button,
            self.bulleted_button,
            self.numbered_button,
        )
        formatting = QWidget()
        formatting.setAccessibleName(tr("Formatting"))
        formatting_layout = QHBoxLayout(formatting)
        formatting_layout.setContentsMargins(0, 0, 0, 0)
        for button in self._format_buttons:
            formatting_layout.addWidget(button)
        formatting_layout.addStretch()

        style = QLabel(style_label)
        style.setBuddy(self.style_combo)
        form.addRow(style, self.style_combo)
        form.addRow(tr("Formatting"), formatting)
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


class FormatButton(QToolButton):
    """A checkable formatting button showing an icon, named in words.

    The words stay the button's text, so screen readers announce "Bold" (and its
    checked state); only the picture is shown. The icon is drawn in the theme's
    text color, sized to the font, and redrawn when either changes.
    """

    def __init__(self, text: str, icon_name: str, shortcut: str) -> None:
        super().__init__()
        self.icon_name = icon_name
        self.setText(text)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setCheckable(True)
        # Reachable with Tab like any other control; QToolButton defaults to
        # mouse-only focus.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        shortcut_text = QKeySequence(shortcut).toString(
            QKeySequence.SequenceFormat.NativeText
        )
        self.setToolTip(f"{text} ({shortcut_text})")
        self.setAccessibleName(text)
        self.setAccessibleDescription(tr("Shortcut: {keys}").format(keys=shortcut_text))
        self._draw_icon()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt override)
        if event.type() in {QEvent.Type.PaletteChange, QEvent.Type.FontChange}:
            self._draw_icon()
        super().changeEvent(event)

    def _draw_icon(self) -> None:
        # As tall as a line of text, so it grows with large system fonts.
        size = max(self.fontMetrics().height() + ICON_EXTRA_PX, MIN_ICON_PX)
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        self.setIconSize(QSize(size, size))
        self.setIcon(format_icon(self.icon_name, color, size, self.devicePixelRatioF()))
