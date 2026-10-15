"""The shared dialogs: what Enter (the default) and Escape choose in each."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QWidget

from omr_data_collector.ui.form_helpers import (
    ask,
    ask_save_first,
    confirm_despite_problems,
    confirm_destructive,
    message_box,
    tell,
    warn,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot


@pytest.fixture
def parent(qtbot: QtBot) -> QWidget:
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


def answer_with(mocker: MockerFixture, pick: Callable[[QMessageBox], object]) -> dict:
    """Make the next message box "click" what ``pick`` returns; record the box."""
    seen: dict = {}

    def run(box: QMessageBox) -> int:
        seen["text"] = box.text()
        seen["default"] = box.defaultButton().text()
        seen["escape"] = box.escapeButton().text()
        mocker.patch.object(box, "clickedButton", return_value=pick(box))
        return 0

    mocker.patch.object(QMessageBox, "exec", run)
    return seen


def button(text: str) -> Callable[[QMessageBox], object]:
    return lambda box: next(
        b for b in box.buttons() if b.text().replace("&", "") == text
    )


def test_save_first_defaults_to_save(parent: QWidget, mocker: MockerFixture) -> None:
    seen = answer_with(mocker, button("Save"))

    assert ask_save_first(parent, "Save it to print it?")
    assert seen["default"].replace("&", "") == "Save"
    assert seen["escape"].replace("&", "") == "Cancel"


def test_save_first_cancelled(parent: QWidget, mocker: MockerFixture) -> None:
    answer_with(mocker, button("Cancel"))

    assert not ask_save_first(parent, "Save it to print it?")


@pytest.mark.parametrize(
    ("clicked", "expected"), [("Go ahead anyway", True), ("Cancel", False)]
)
def test_problems_default_to_cancel(
    parent: QWidget,
    mocker: MockerFixture,
    clicked: str,
    expected: bool,  # noqa: FBT001
) -> None:
    seen = answer_with(mocker, button(clicked))

    result = confirm_despite_problems(
        parent, "Check before you print it:", ["Too wide.", "Too tall."]
    )

    assert result is expected
    assert seen["text"] == "Check before you print it:\n\n- Too wide.\n- Too tall."
    assert seen["default"].replace("&", "") == "Cancel"


@pytest.mark.parametrize(("clicked", "expected"), [("Delete", True), ("Cancel", False)])
def test_destructive_actions_default_to_cancel(
    parent: QWidget,
    mocker: MockerFixture,
    clicked: str,
    expected: bool,  # noqa: FBT001
) -> None:
    seen = answer_with(mocker, button(clicked))

    assert confirm_destructive(parent, "Delete", "Delete it?", "Delete") is expected
    assert seen["default"].replace("&", "") == "Cancel"
    assert seen["escape"].replace("&", "") == "Cancel"


def test_tell_shows_the_message(parent: QWidget, mocker: MockerFixture) -> None:
    seen: dict = {}
    mocker.patch.object(
        QMessageBox, "exec", lambda box: seen.setdefault("text", box.text())
    )

    tell(parent, "Title", "Enter the details first.")

    assert seen["text"] == "Enter the details first."


def test_names_that_look_like_html_show_as_typed(parent: QWidget) -> None:
    name = '<a href="https://example.com">Intake</a>'

    box = message_box(
        parent, QMessageBox.Icon.Question, "Delete", f'Delete "{name}"?', name
    )

    assert box.textFormat() == Qt.TextFormat.PlainText
    shown = [label for label in box.findChildren(QLabel) if "Intake" in label.text()]
    assert len(shown) == 2  # the question and its details
    assert all(label.textFormat() == Qt.TextFormat.PlainText for label in shown)


@pytest.mark.parametrize(
    ("clicked", "expected"), [("Second", 1), ("Cancel", 2), (None, None)]
)
def test_ask_returns_the_answer_chosen(
    parent: QWidget, mocker: MockerFixture, clicked: str | None, expected: int | None
) -> None:
    seen = answer_with(mocker, button(clicked) if clicked else lambda _box: None)

    chosen = ask(
        parent,
        "Title",
        "Which?",
        ["&First", "&Second", QMessageBox.StandardButton.Cancel],
        default=1,
        escape=2,
    )

    assert chosen == expected
    assert seen["default"].replace("&", "") == "Second"
    assert seen["escape"].replace("&", "") == "Cancel"


def test_warn_shows_the_problem_as_plain_text(
    parent: QWidget, mocker: MockerFixture
) -> None:
    seen: dict = {}
    mocker.patch.object(
        QMessageBox,
        "exec",
        lambda box: seen.update(text=box.text(), plain=box.textFormat()),
    )

    warn(parent, "Couldn't save", "<b>disk full</b>")

    assert seen == {"text": "<b>disk full</b>", "plain": Qt.TextFormat.PlainText}
