from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QMimeData
from PySide6.QtGui import QTextCursor, QTextListFormat

from omr_data_collector.ui.TextBlockEditor import TextBlockEditor

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot


@pytest.fixture
def editor(qtbot: QtBot) -> TextBlockEditor:
    widget = TextBlockEditor()
    qtbot.addWidget(widget)
    return widget


def place_cursor(editor: TextBlockEditor, block_number: int, *, lines: int = 1) -> None:
    """Put the cursor in a paragraph, selecting ``lines`` paragraphs from there."""
    cursor = QTextCursor(editor.document().findBlockByNumber(block_number))
    for _ in range(lines - 1):
        cursor.movePosition(
            QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor
        )
    editor.setTextCursor(cursor)


def select_all(editor: TextBlockEditor) -> None:
    cursor = editor.textCursor()
    cursor.select(QTextCursor.SelectionType.Document)
    editor.setTextCursor(cursor)


def test_markdown_round_trips(editor: TextBlockEditor) -> None:
    markdown = "# Intake\n\nSome **bold** and *italic* text.\n\n- one\n- two\n"

    editor.set_markdown(markdown)

    assert editor.markdown().strip() == markdown.strip()


def test_raw_html_is_kept_as_text_not_markup(editor: TextBlockEditor) -> None:
    editor.set_markdown("<b>not bold</b>")

    assert editor.toPlainText() == "<b>not bold</b>"
    assert "**" not in editor.markdown()


def test_bold_and_italic(editor: TextBlockEditor) -> None:
    editor.setPlainText("Fill in every row")
    select_all(editor)

    editor.set_bold(on=True)
    editor.set_italic(on=True)

    assert editor.markdown().strip() == "***Fill in every row***"


@pytest.mark.parametrize("level", [1, 2, 3])
def test_heading_levels(editor: TextBlockEditor, level: int) -> None:
    editor.setPlainText("Intake form\nBody")
    place_cursor(editor, 0)

    editor.set_heading_level(level)

    assert editor.heading_level() == level
    assert editor.markdown().startswith(f"{'#' * level} Intake form\n")


def test_heading_back_to_normal_text_keeps_italics(editor: TextBlockEditor) -> None:
    editor.set_markdown("Intake *form*\n")
    place_cursor(editor, 0)
    editor.set_heading_level(1)

    editor.set_heading_level(0)

    assert editor.heading_level() == 0
    assert editor.markdown().strip() == "Intake *form*"


def test_bulleted_and_numbered_lists_toggle(editor: TextBlockEditor) -> None:
    editor.setPlainText("Intro\nfirst\nsecond")
    place_cursor(editor, 1, lines=2)

    editor.toggle_list(QTextListFormat.Style.ListDisc)
    assert "- first\n- second" in editor.markdown()
    assert editor.list_style() == QTextListFormat.Style.ListDisc

    editor.toggle_list(QTextListFormat.Style.ListDecimal)
    assert "1.  first\n2.  second" in editor.markdown()

    editor.toggle_list(QTextListFormat.Style.ListDecimal)
    assert editor.list_style() is None
    assert "first" in editor.markdown()
    assert "1." not in editor.markdown()


def test_paste_keeps_only_what_markdown_can_store(editor: TextBlockEditor) -> None:
    mime = QMimeData()
    mime.setHtml(
        '<h2 style="color:red">Welcome</h2>'
        '<p><span style="font-size:30px; font-family:Comic Sans MS">'
        "<b>Read this</b></span> <img src='file:///home/someone/logo.png'></p>"
    )

    editor.insertFromMimeData(mime)

    assert editor.markdown().strip() == "## Welcome\n\n**Read this**"


def test_plain_text_paste_is_inserted_as_is(editor: TextBlockEditor) -> None:
    mime = QMimeData()
    mime.setText("plain *not markdown*")

    editor.insertFromMimeData(mime)

    assert editor.toPlainText() == "plain *not markdown*"


def test_tab_moves_focus_instead_of_typing_a_tab(editor: TextBlockEditor) -> None:
    assert editor.tabChangesFocus()
