from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QAbstractSpinBox, QTableWidgetItem

from omr_data_collector.constants import (
    ANSWER_TYPES,
    PAGE_ORIENTATIONS,
    WRITTEN_DATA_TYPES,
)
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Organization import Organization
from omr_data_collector.models.TableBlock import Column, TableBlock
from omr_data_collector.storage.organization_store import save_organization
from omr_data_collector.storage.table_block_store import (
    list_table_blocks,
    save_table_block,
)
from omr_data_collector.ui.ColumnDialog import ColumnDialog
from omr_data_collector.ui.TableBlocksPage import TableBlocksPage, column_summary

if TYPE_CHECKING:
    import sqlite3

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

PAGE_MODULE = "omr_data_collector.ui.TableBlocksPage"

TIME = Column(
    "time",
    "HH:MM",
    AnswerSpec(
        ANSWER_TYPES.WRITTEN,
        data_type=WRITTEN_DATA_TYPES.DATE_TIME,
        date_time_format="HH:MM",
    ),
)
VISIT = Column(
    "first_visit",
    answer=AnswerSpec(
        ANSWER_TYPES.YES_NO, choices=(Choice("Y", "yes"), Choice("N", "no"))
    ),
)
SERVICES = Column(
    "services",
    answer=AnswerSpec(
        ANSWER_TYPES.MANY_CHOICES,
        choices=(
            Choice("Food", "Food"),
            Choice("Clothes", "Clothes"),
            Choice("Other", "Other"),
        ),
    ),
)


def make_page(qtbot: QtBot, connection: sqlite3.Connection) -> TableBlocksPage:
    page = TableBlocksPage(connection)
    qtbot.addWidget(page)
    return page


def column_names(page: TableBlocksPage) -> list[str]:
    return [column.name for column in page.read_item("t", "x").columns]


def dialog_returns(mocker: MockerFixture, *columns: Column | None):
    """Stand in for the column dialog, answering with ``columns`` in turn."""
    return mocker.patch(f"{PAGE_MODULE}.edit_column", side_effect=list(columns))


# --- Columns ----------------------------------------------------------------------


def test_add_columns_and_save_the_table(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    page = make_page(qtbot, connection)
    page.name_edit.setText("Visit log")
    page.text_fields.editor.setPlainText("One row per visit.")
    page.rows_spin.setValue(25)
    dialog_returns(mocker, TIME, VISIT)

    page.add_column()
    page.add_column()
    page.save()

    (saved,) = list_table_blocks(connection)
    assert saved.rows == 25
    assert saved.instructions.strip() == "One row per visit."
    assert [column.name for column in saved.columns] == ["time", "first_visit"]
    assert page.column_list.item(1).text() == "first_visit (pick one: Y, N)"


def test_cancelling_the_dialog_adds_nothing(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    page = make_page(qtbot, connection)
    dialog_returns(mocker, None)

    page.add_column()

    assert column_names(page) == []
    assert not page.has_unsaved_changes()


def test_the_dialog_is_told_the_other_column_names(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_table_block(connection, TableBlock(name="t", columns=(TIME, VISIT)))
    page = make_page(qtbot, connection)
    page.column_list.setCurrentRow(1)
    edit = dialog_returns(mocker, None)

    page.edit_selected_column()

    parent, column, other_names = edit.call_args.args
    assert parent is page
    assert column == VISIT.normalized()
    assert other_names == {"time"}


def test_edit_remove_and_reorder_columns(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_table_block(connection, TableBlock(name="t", columns=(TIME, VISIT, SERVICES)))
    page = make_page(qtbot, connection)
    renamed = Column("visit_time", TIME.example, TIME.answer)
    dialog_returns(mocker, renamed)

    page.column_list.setCurrentRow(0)
    page.edit_selected_column()
    page.column_list.setCurrentRow(2)
    page.move_selected_column(-1)
    assert column_names(page) == ["visit_time", "services", "first_visit"]
    assert page.column_list.currentRow() == 1

    page.remove_selected_column()
    assert column_names(page) == ["visit_time", "first_visit"]
    assert page.has_unsaved_changes()


def test_column_buttons_follow_the_selection(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    save_table_block(connection, TableBlock(name="t", columns=(TIME, VISIT)))
    page = make_page(qtbot, connection)

    page.column_list.setCurrentRow(0)
    assert not page.move_left_button.isEnabled()
    assert page.move_right_button.isEnabled()

    page.column_list.setCurrentRow(1)
    assert page.move_left_button.isEnabled()
    assert not page.move_right_button.isEnabled()


def test_saving_without_columns_points_at_the_columns_list(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    with qtbot.waitActive(page):
        page.show()
        page.activateWindow()
    page.name_edit.setText("Empty")

    page.save()

    assert page.error_labels["columns"].text() == "Add at least one column."
    assert page.focusWidget() is page.column_list


def test_duplicate_copies_the_columns(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    save_table_block(connection, TableBlock(name="Visit log", rows=7, columns=(TIME,)))
    page = make_page(qtbot, connection)

    page.duplicate_item()

    copy = next(
        t for t in list_table_blocks(connection) if t.name == "Visit log (copy)"
    )
    assert copy.rows == 7
    assert copy.columns == (TIME.normalized(),)


def test_saved_tables_load_without_unsaved_changes(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    save_table_block(
        connection,
        TableBlock(
            name="t", instructions="**Bold**", rows=3, columns=(TIME, VISIT, SERVICES)
        ),
    )

    page = make_page(qtbot, connection)

    assert not page.has_unsaved_changes()


@pytest.mark.parametrize(
    ("column", "summary"),
    [
        (TIME, "time (written date/time, HH:MM)"),
        (SERVICES, "services (pick any: Food, Clothes, Other)"),
        (
            Column(
                "id",
                answer=AnswerSpec(
                    ANSWER_TYPES.WRITTEN,
                    data_type=WRITTEN_DATA_TYPES.ID,
                    max_characters=6,
                ),
            ),
            "id (written id, 6 characters)",
        ),
    ],
)
def test_column_summaries(column: Column, summary: str) -> None:
    assert column_summary(column.normalized()) == summary


# --- Preview --------------------------------------------------------------------


def test_preview_starts_on_the_organizations_orientation(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    save_organization(
        connection,
        Organization(name="Food Bank", orientation=PAGE_ORIENTATIONS.LANDSCAPE),
    )
    save_table_block(connection, TableBlock(name="t", columns=(TIME,)))

    page = make_page(qtbot, connection)

    assert page.preview_orientation_combo.currentData() == PAGE_ORIENTATIONS.LANDSCAPE
    assert page.preview_summary.text().startswith("Fits on Letter landscape")


def test_preview_summary_follows_changes(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    page = make_page(qtbot, connection)
    assert page.preview_summary.text() == (
        "Add columns to preview the table on Letter portrait."
    )
    wide = Column("notes", answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=40))
    dialog_returns(mocker, wide)

    page.add_column()
    assert page.preview_summary.text().startswith("Too wide for Letter portrait")

    page.preview_orientation_combo.setCurrentIndex(
        page.preview_orientation_combo.findData(PAGE_ORIENTATIONS.LANDSCAPE)
    )
    assert page.preview_summary.text().startswith("Fits on Letter landscape")


def test_preview_describes_itself_to_screen_readers(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    save_table_block(connection, TableBlock(name="t", columns=(TIME,)))
    page = make_page(qtbot, connection)

    interface = QAccessible.queryAccessibleInterface(page.preview)

    assert interface.text(QAccessible.Text.Name) == "Table preview"
    assert interface.text(QAccessible.Text.Description) == page.preview_summary.text()


def test_preview_paints(qtbot: QtBot, connection: sqlite3.Connection) -> None:
    save_table_block(
        connection, TableBlock(name="t", rows=40, columns=(TIME, VISIT, SERVICES))
    )
    page = make_page(qtbot, connection)
    page.preview.resize(300, 380)

    image = page.preview.grab().toImage()

    assert not image.isNull()


# --- Keyboard and screen readers --------------------------------------------------


def test_delete_in_the_columns_list_removes_a_column_not_the_table(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_table_block(connection, TableBlock(name="t", columns=(TIME, VISIT)))
    page = make_page(qtbot, connection)
    with qtbot.waitActive(page):
        page.show()
        page.activateWindow()
    confirm = mocker.patch(
        "omr_data_collector.ui.LibraryPage.confirm_destructive", return_value=False
    )
    page.column_list.setFocus()
    page.column_list.setCurrentRow(0)

    qtbot.keyClick(page.column_list, Qt.Key.Key_Delete)

    confirm.assert_not_called()
    assert column_names(page) == ["first_visit"]


def test_enter_on_a_column_opens_it(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_table_block(connection, TableBlock(name="t", columns=(TIME,)))
    page = make_page(qtbot, connection)
    edit = dialog_returns(mocker, None)
    page.column_list.setCurrentRow(0)

    page.column_list.itemActivated.emit(page.column_list.item(0))

    edit.assert_called_once()


def test_fields_are_labelled_and_mnemonics_unique(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    for key, label in page.field_labels.items():
        interface = QAccessible.queryAccessibleInterface(page.field_widgets[key])
        labels = [
            related.text(QAccessible.Text.Name)
            for related, _ in interface.relations(QAccessible.RelationFlag.Label)
        ]
        assert labels[0] == label.text().replace("&", ""), key

    texts = [
        "Table li&brary",
        "St&yle",
        "&Preview on",
        *(label.text() for label in page.field_labels.values()),
        *(
            button.text()
            for button in (
                page.new_button,
                page.duplicate_button,
                page.delete_button,
                page.save_button,
                page.revert_button,
                page.add_column_button,
                page.edit_column_button,
                page.remove_column_button,
                page.move_left_button,
                page.move_right_button,
            )
        ),
    ]
    mnemonics = [text[text.index("&") + 1].lower() for text in texts]
    assert len(mnemonics) == len(set(mnemonics)), mnemonics


def test_tab_order_follows_the_screen(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    fields = page.text_fields
    expected = [
        page.item_list,
        page.new_button,
        page.duplicate_button,
        page.delete_button,
        page.name_edit,
        fields.style_combo,
        fields.bold_button,
        fields.italic_button,
        fields.bulleted_button,
        fields.numbered_button,
        fields.editor,
        page.rows_spin,
        page.column_list,
        page.add_column_button,
        page.edit_column_button,
        page.remove_column_button,
        page.move_left_button,
        page.move_right_button,
        page.preview_orientation_combo,
        page.revert_button,
        page.save_button,
    ]

    chain = [expected[0]]
    widget = expected[0]
    while len(chain) < len(expected):
        widget = widget.nextInFocusChain()
        inside_spin_box = isinstance(widget.parentWidget(), QAbstractSpinBox)
        if widget.focusPolicy() & Qt.FocusPolicy.TabFocus and not inside_spin_box:
            chain.append(widget)

    assert chain == expected


def test_the_form_scrolls_to_follow_keyboard_focus(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    page.resize(900, 300)
    with qtbot.waitActive(page):
        page.show()
        page.activateWindow()
    scroll_bar = page.form_scroll.verticalScrollBar()
    assert scroll_bar.value() == 0

    page.preview_orientation_combo.setFocus()

    assert scroll_bar.value() > 0


# --- Column dialog --------------------------------------------------------------


def make_dialog(
    qtbot: QtBot,
    column: Column | None = None,
    other_names: frozenset[str] = frozenset(),
) -> ColumnDialog:
    dialog = ColumnDialog(None, column, set(other_names))
    qtbot.addWidget(dialog)
    return dialog


def test_dialog_returns_the_entered_column(qtbot: QtBot) -> None:
    dialog = make_dialog(qtbot)
    dialog.name_edit.setText(" first_visit ")
    table = dialog.answer_fields.choices_table
    table.setItem(0, 0, QTableWidgetItem("Y"))
    table.setItem(1, 0, QTableWidgetItem("N"))

    dialog.accept()

    assert dialog.column() == Column(
        "first_visit",
        answer=AnswerSpec(
            ANSWER_TYPES.YES_NO, choices=(Choice("Y", "Y"), Choice("N", "N"))
        ),
    )


def test_dialog_stays_open_until_the_column_is_valid(qtbot: QtBot) -> None:
    dialog = make_dialog(qtbot, other_names=frozenset({"time"}))
    with qtbot.waitActive(dialog):
        dialog.show()
        dialog.activateWindow()
    dialog.name_edit.setText("TIME")

    dialog.accept()

    assert dialog.column() is None
    assert dialog.isVisible()
    assert dialog.error_labels["name"].text() == (
        'This table already has a column called "TIME".'
    )
    assert dialog.focusWidget() is dialog.name_edit


def test_dialog_edits_an_existing_column(qtbot: QtBot) -> None:
    dialog = make_dialog(qtbot, SERVICES.normalized())

    assert dialog.windowTitle() == "Edit column"
    assert dialog.entered_column() == SERVICES.normalized()


def test_dialog_fields_are_labelled_with_unique_mnemonics(qtbot: QtBot) -> None:
    dialog = make_dialog(qtbot)
    fields = dialog.answer_fields
    texts = [
        *(label.text() for label in dialog.field_labels.values()),
        *(
            button.text()
            for button in (
                fields.add_choice_button,
                fields.remove_choice_button,
                fields.move_up_button,
                fields.move_down_button,
            )
        ),
    ]

    mnemonics = [text[text.index("&") + 1].lower() for text in texts]

    assert len(mnemonics) == len(set(mnemonics)), mnemonics
