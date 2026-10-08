from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible, QColor, QPalette
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from omr_data_collector.models.Organization import Organization
from omr_data_collector.storage.organization_store import save_organization
from omr_data_collector.ui.accessibility import (
    MIN_TEXT_CONTRAST,
    announce,
    contrast_ratio,
    error_text_color,
    set_field_error,
)
from omr_data_collector.ui.MainWindow import MainWindow
from omr_data_collector.ui.OrganizationPage import FORM_FIELDS, OrganizationPage

if TYPE_CHECKING:
    import sqlite3

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot


def accessible_name(widget) -> str:
    interface = QAccessible.queryAccessibleInterface(widget)
    return interface.text(QAccessible.Text.Name)


def accessible_description(widget) -> str:
    interface = QAccessible.queryAccessibleInterface(widget)
    return interface.text(QAccessible.Text.Description)


def make_page(qtbot: QtBot, connection: sqlite3.Connection) -> OrganizationPage:
    page = OrganizationPage(connection)
    qtbot.addWidget(page)
    return page


# --- Contrast -------------------------------------------------------------------


def test_contrast_ratio_matches_wcag_reference_values() -> None:
    assert contrast_ratio(QColor("black"), QColor("white")) == pytest.approx(21)
    assert contrast_ratio(QColor("white"), QColor("white")) == pytest.approx(1)
    # WCAG's own example: #767676 on white is just above 4.5:1.
    assert contrast_ratio(QColor("#767676"), QColor("white")) == pytest.approx(
        4.54, abs=0.01
    )


@pytest.mark.parametrize(
    "background",
    ["#ffffff", "#efefef", "#d6d6d6", "#3c3c3c", "#202020", "#000000"],
)
def test_error_color_is_readable_on_light_and_dark_backgrounds(
    background: str,
) -> None:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(background))

    color = error_text_color(palette)

    assert contrast_ratio(color, QColor(background)) >= MIN_TEXT_CONTRAST


def test_error_color_falls_back_to_theme_text_when_no_red_is_readable() -> None:
    # A mid-grey background where neither red reaches 4.5:1, as on some themes.
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#8a8a8a"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#000000"))

    assert error_text_color(palette) == QColor("#000000")


def test_set_field_error_shows_the_message_and_describes_the_field(
    qtbot: QtBot,
) -> None:
    container = QWidget()
    qtbot.addWidget(container)
    form = QFormLayout(container)
    field, label = QLineEdit(), QLabel()
    form.addRow("Phone", field)
    form.addRow("", label)

    set_field_error(form, field, label, "Enter a phone number.")
    assert label.text() == "Enter a phone number."
    assert form.isRowVisible(label)
    assert field.accessibleDescription() == "Enter a phone number."

    set_field_error(form, field, label, "")
    assert not form.isRowVisible(label)
    assert field.accessibleDescription() == ""


@pytest.mark.usefixtures("qapp")
def test_announce_sends_an_announcement_event(mocker: MockerFixture) -> None:
    update = mocker.patch.object(QAccessible, "updateAccessibility")
    source = QLabel()

    announce(source, "Organization saved.", assertive=True)

    (event,) = update.call_args.args
    assert event.message() == "Organization saved."
    assert event.politeness() == QAccessible.AnnouncementPoliteness.Assertive


# --- Organization page ----------------------------------------------------------


def labelled_by(widget) -> list[str]:
    """The texts of the labels screen readers are told name ``widget``.

    From the field's side Qt calls this the Label relation: the related object is
    a label for this one. The group box around the field is also listed, which is
    how screen readers announce the group.
    """
    interface = QAccessible.queryAccessibleInterface(widget)
    return [
        related.text(QAccessible.Text.Name)
        for related, _ in interface.relations(QAccessible.RelationFlag.Label)
    ]


def test_every_input_is_labelled_for_screen_readers(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)

    for field_name, label_text, _ in FORM_FIELDS:
        widget = page.field_widgets[field_name]
        assert page.field_labels[field_name].buddy() is widget
        assert labelled_by(widget)[0] == label_text.replace("&", "")


def test_required_is_stated_in_the_label_not_only_a_placeholder(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)

    assert labelled_by(page.name_edit)[0] == "Organization name (required)"
    assert page.name_edit.placeholderText() == ""


def test_mnemonics_are_unique(qtbot: QtBot, connection: sqlite3.Connection) -> None:
    page = make_page(qtbot, connection)
    texts = [label for _, label, _ in FORM_FIELDS] + [
        button.text()
        for button in (
            page.save_button,
            page.revert_button,
            page.save_qr_button,
            page.print_qr_button,
        )
    ]

    mnemonics = [text[text.index("&") + 1].lower() for text in texts]

    assert len(mnemonics) == len(set(mnemonics)), mnemonics


def test_tab_order_follows_the_screen(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    expected = [
        *(page.field_widgets[name] for name, _, _ in FORM_FIELDS),
        page.revert_button,
        page.save_button,
        page.save_qr_button,
        page.print_qr_button,
    ]

    # Tab passes over widgets that don't take keyboard focus, such as labels.
    chain = [expected[0]]
    widget = expected[0]
    while len(chain) < len(expected):
        widget = widget.nextInFocusChain()
        if widget.focusPolicy() & Qt.FocusPolicy.TabFocus:
            chain.append(widget)

    assert chain == expected


def test_failed_save_focuses_the_first_invalid_field_and_describes_the_error(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    with qtbot.waitActive(page):
        page.show()
        page.activateWindow()
    page.name_edit.setText("Food Bank")
    page.phone_edit.setText("555")
    page.email_edit.setText("info@example")
    page.save_button.setFocus()

    with qtbot.waitSignal(page.status_message) as status:
        page.save()

    assert page.focusWidget() is page.phone_edit
    assert accessible_description(page.phone_edit).startswith("Enter a phone number")
    assert accessible_description(page.email_edit).startswith("Enter an email")
    assert status.args == ["2 fields to fix before saving."]


def test_fixed_errors_are_removed_from_the_description(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    page.save()
    assert accessible_description(page.name_edit)

    page.name_edit.setText("Food Bank")
    page.save()

    assert accessible_description(page.name_edit) == ""


def test_ctrl_s_saves(qtbot: QtBot, connection: sqlite3.Connection) -> None:
    page = make_page(qtbot, connection)
    with qtbot.waitActive(page):
        page.show()
        page.activateWindow()
    page.name_edit.setFocus()
    page.name_edit.setText("Food Bank")

    with qtbot.waitSignal(page.status_message) as status:
        qtbot.keyClick(
            page.name_edit, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier
        )

    assert status.args == ["Organization saved."]


def test_qr_code_image_is_described(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    assert accessible_name(page.qr_preview) == "QR code"
    assert accessible_description(page.qr_preview) == "Not created yet."

    page.name_edit.setText("Food Bank")
    page.save()

    assert "Identifies Food Bank" in accessible_description(page.qr_preview)


def test_error_color_is_rechosen_when_the_theme_changes(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor("#202020"))

    page.setPalette(dark)

    style = page.error_labels["name"].styleSheet()
    assert error_text_color(dark).name() in style
    assert contrast_ratio(error_text_color(dark), QColor("#202020")) >= (
        MIN_TEXT_CONTRAST
    )


# --- Main window ----------------------------------------------------------------


def test_status_messages_are_announced(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_organization(connection, Organization(name="Food Bank"))
    window = MainWindow(connection)
    qtbot.addWidget(window)
    announce_mock = mocker.patch("omr_data_collector.ui.MainWindow.announce")

    window.organization_page.status_message.emit("Organization saved.")

    announce_mock.assert_called_once_with(window, "Organization saved.")
    assert window.statusBar().currentMessage() == "Organization saved."
