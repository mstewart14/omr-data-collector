from __future__ import annotations

import re
from typing import TYPE_CHECKING

from PySide6.QtGui import (
    QFont,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
    QTextFormat,
    QTextListFormat,
)
from PySide6.QtWidgets import QTextEdit

if TYPE_CHECKING:
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QTextBlock

# GitHub-flavoured Markdown without raw HTML: anything HTML-like is kept as literal
# text, so a stored block can only ever hold the formatting the toolbar offers.
MARKDOWN_FEATURES = (
    QTextDocument.MarkdownFeature.MarkdownDialectGitHub
    | QTextDocument.MarkdownFeature.MarkdownNoHTML
)

HEADING_LEVELS = (1, 2, 3)
# Qt's Markdown importer sizes headings this way (level 1 largest), so headings set
# from the toolbar look the same as ones loaded from saved Markdown.
HEADING_SIZE_ADJUSTMENT = {1: 3, 2: 2, 3: 1}

# Pasted images are dropped: blocks are text, and an image link would point at a
# file on someone's computer that the form builder couldn't print.
MARKDOWN_IMAGE_REGEX = re.compile(r"!\[[^\]]*\]\([^)]*\)")


class TextBlockEditor(QTextEdit):
    """Edits a text block's formatted text, limited to what Markdown can store."""

    def __init__(self) -> None:
        super().__init__()
        # Tab moves on to the next control, as everywhere else in the app, so
        # keyboard users never get stuck in the editor; lists are made from the
        # toolbar instead of by indenting with Tab.
        self.setTabChangesFocus(True)

    def markdown(self) -> str:
        # Qt writes ** and * from the font it actually resolved, not the formatting
        # requested, so bold and italic need real fonts installed. Every desktop
        # has them; tests/conftest.py supplies them to offscreen Qt on Windows.
        return self.document().toMarkdown(MARKDOWN_FEATURES)

    def set_markdown(self, text: str) -> None:
        self.document().setMarkdown(text, MARKDOWN_FEATURES)

    def set_bold(self, *, on: bool) -> None:
        char_format = QTextCharFormat()
        char_format.setFontWeight(QFont.Weight.Bold if on else QFont.Weight.Normal)
        self.mergeCurrentCharFormat(char_format)

    def set_italic(self, *, on: bool) -> None:
        char_format = QTextCharFormat()
        char_format.setFontItalic(on)
        self.mergeCurrentCharFormat(char_format)

    def heading_level(self) -> int:
        """The current paragraph's heading level; 0 for ordinary text."""
        return self.textCursor().blockFormat().headingLevel()

    def set_heading_level(self, level: int) -> None:
        """Make the selected paragraphs headings of ``level``, or ordinary text at 0."""
        cursor = self.textCursor()
        cursor.beginEditBlock()
        for block in _selected_blocks(cursor):
            was_heading = block.blockFormat().headingLevel() > 0
            block_cursor = QTextCursor(block)
            block_format = block.blockFormat()
            block_format.setHeadingLevel(level)
            block_cursor.setBlockFormat(block_format)
            _restyle_heading_text(block, level, was_heading=was_heading)
        cursor.endEditBlock()

    def list_style(self) -> QTextListFormat.Style | None:
        text_list = self.textCursor().currentList()
        return text_list.format().style() if text_list else None

    def toggle_list(self, style: QTextListFormat.Style) -> None:
        """Make the selected paragraphs a list of ``style``, or plain if they are one."""
        cursor = self.textCursor()
        text_list = cursor.currentList()
        cursor.beginEditBlock()
        if text_list is None:
            cursor.createList(style)
        elif text_list.format().style() == style:
            for block in _selected_blocks(cursor):
                block_list = block.textList()
                if block_list is not None:
                    block_list.remove(block)
                block_format = block.blockFormat()
                block_format.setIndent(0)
                QTextCursor(block).setBlockFormat(block_format)
        else:
            list_format = text_list.format()
            list_format.setStyle(style)
            text_list.setFormat(list_format)
        cursor.endEditBlock()

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802 (Qt override)
        # Pasted rich text (from a word processor or web page) keeps only what
        # Markdown can store: bold, italic, headings and lists. Fonts, colors and
        # images are dropped, so what's on screen is exactly what will be saved.
        if not source.hasHtml():
            super().insertFromMimeData(source)
            return
        pasted = QTextDocument()
        pasted.setHtml(source.html())
        markdown = MARKDOWN_IMAGE_REGEX.sub("", pasted.toMarkdown(MARKDOWN_FEATURES))
        cleaned = QTextDocument()
        cleaned.setMarkdown(markdown, MARKDOWN_FEATURES)
        self.textCursor().insertFragment(QTextDocumentFragment(cleaned))


def _selected_blocks(cursor: QTextCursor) -> list[QTextBlock]:
    document = cursor.document()
    first = document.findBlock(cursor.selectionStart())
    last = document.findBlock(cursor.selectionEnd())
    blocks = [first]
    while blocks[-1] != last and blocks[-1].next().isValid():
        blocks.append(blocks[-1].next())
    return blocks


def _restyle_heading_text(block: QTextBlock, level: int, *, was_heading: bool) -> None:
    """Size and embolden a heading's text, or undo that for ordinary text.

    Turning a heading back into ordinary text clears only the size and boldness
    the heading added, run by run, so italics inside it survive.
    """
    if level:
        char_format = QTextCharFormat()
        char_format.setProperty(
            QTextFormat.Property.FontSizeAdjustment, HEADING_SIZE_ADJUSTMENT[level]
        )
        char_format.setFontWeight(QFont.Weight.Bold)
        cursor = QTextCursor(block)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        cursor.mergeCharFormat(char_format)
        cursor.mergeBlockCharFormat(char_format)
        return
    if not was_heading:
        return

    iterator = block.begin()
    while not iterator.atEnd():
        fragment = iterator.fragment()
        char_format = fragment.charFormat()
        char_format.clearProperty(QTextFormat.Property.FontSizeAdjustment)
        char_format.clearProperty(QTextFormat.Property.FontWeight)
        cursor = QTextCursor(block.document())
        cursor.setPosition(fragment.position())
        cursor.setPosition(
            fragment.position() + fragment.length(), QTextCursor.MoveMode.KeepAnchor
        )
        # setCharFormat, not merge: merging can't remove properties.
        cursor.setCharFormat(char_format)
        iterator += 1
    block_format = block.charFormat()
    block_format.clearProperty(QTextFormat.Property.FontSizeAdjustment)
    block_format.clearProperty(QTextFormat.Property.FontWeight)
    QTextCursor(block).setBlockCharFormat(block_format)
