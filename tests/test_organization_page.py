from __future__ import annotations

import json
from typing import TYPE_CHECKING

import cv2
import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QPageLayout, QPdfWriter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QDialog, QFileDialog

from omr_data_collector.constants import PAGE_ORIENTATIONS, PAPER_SIZES
from omr_data_collector.identity.qr_code import read_qr_codes
from omr_data_collector.layout.page_setup import page_layout
from omr_data_collector.models.Organization import Organization
from omr_data_collector.storage.organization_store import (
    load_organization,
    save_organization,
)
from omr_data_collector.ui.OrganizationPage import OrganizationPage
from omr_data_collector.ui.qr_printing import paint_organization_qr_page

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

PAGE_MODULE = "omr_data_collector.ui.OrganizationPage"


def make_page(qtbot: QtBot, connection: sqlite3.Connection) -> OrganizationPage:
    page = OrganizationPage(connection)
    qtbot.addWidget(page)
    return page


def test_new_installation_starts_blank_with_letter_portrait(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)

    assert page.name_edit.text() == ""
    assert page.paper_size_combo.currentData() == PAPER_SIZES.LETTER
    assert page.orientation_combo.currentData() == PAGE_ORIENTATIONS.PORTRAIT
    assert not page.save_button.isEnabled()
    assert not page.save_qr_button.isEnabled()
    assert not page.print_qr_button.isEnabled()
    assert page.qr_preview.pixmap().isNull()


def test_saving_requires_a_name(qtbot: QtBot, connection: sqlite3.Connection) -> None:
    page = make_page(qtbot, connection)
    page.phone_edit.setText("613-555-0123")

    page.save()

    assert page.error_labels["name"].isVisibleTo(page)
    assert load_organization(connection) is None


def test_saving_stores_normalized_details_and_shows_the_qr_code(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    page.name_edit.setText("  Food Bank ")
    page.url_edit.setText("example.org")
    page.paper_size_combo.setCurrentIndex(page.paper_size_combo.findData("A4"))

    with qtbot.waitSignal(page.status_message) as status:
        page.save()

    saved = load_organization(connection)
    assert saved is not None
    assert saved.name == "Food Bank"
    assert saved.url == "https://example.org"
    assert saved.paper_size == PAPER_SIZES.A4
    assert status.args == ["Organization saved."]
    assert page.url_edit.text() == "https://example.org"
    assert not page.save_button.isEnabled()
    assert page.save_qr_button.isEnabled()
    assert not page.qr_preview.pixmap().isNull()


def test_invalid_fields_show_errors_until_fixed(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    page = make_page(qtbot, connection)
    page.name_edit.setText("Food Bank")
    page.email_edit.setText("info@example")

    page.save()
    assert page.error_labels["email"].isVisibleTo(page)

    page.email_edit.setText("info@example.org")
    page.save()
    assert not page.error_labels["email"].isVisibleTo(page)
    assert load_organization(connection) is not None


def test_editing_keeps_the_id_and_disables_the_qr_until_saved(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    original = Organization(name="Food Bank")
    save_organization(connection, original)
    page = make_page(qtbot, connection)
    assert page.name_edit.text() == "Food Bank"

    page.name_edit.setText("Community Food Bank")
    assert page.has_unsaved_changes()
    assert page.save_button.isEnabled()
    assert not page.print_qr_button.isEnabled()
    assert page.qr_hint.text() == "Save your changes to update the QR code."

    page.save()

    saved = load_organization(connection)
    assert saved is not None
    assert saved.name == "Community Food Bank"
    assert saved.organization_id == original.organization_id
    assert page.print_qr_button.isEnabled()


def test_revert_restores_the_saved_details(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    save_organization(connection, Organization(name="Food Bank"))
    page = make_page(qtbot, connection)
    page.name_edit.setText("Typo")

    page.revert()

    assert page.name_edit.text() == "Food Bank"
    assert not page.has_unsaved_changes()


def test_whitespace_only_edits_are_not_unsaved_changes(
    qtbot: QtBot, connection: sqlite3.Connection
) -> None:
    save_organization(connection, Organization(name="Food Bank"))
    page = make_page(qtbot, connection)

    page.name_edit.setText("Food Bank ")

    assert not page.has_unsaved_changes()


def test_save_qr_code_writes_the_chosen_file(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture, tmp_path: Path
) -> None:
    organization = Organization(name="Food Bank")
    save_organization(connection, organization)
    page = make_page(qtbot, connection)
    # No extension typed: the one for the chosen file type is added.
    mocker.patch.object(
        QFileDialog,
        "getSaveFileName",
        return_value=(str(tmp_path / "food-bank"), "PNG image (*.png)"),
    )

    page.save_qr_code()

    image = cv2.imread(str(tmp_path / "food-bank.png"), cv2.IMREAD_GRAYSCALE)
    assert image is not None
    (text,) = read_qr_codes(image)
    assert json.loads(text)["organizationId"] == organization.organization_id


def test_save_qr_code_reports_failures(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture, tmp_path: Path
) -> None:
    save_organization(connection, Organization(name="Food Bank"))
    page = make_page(qtbot, connection)
    mocker.patch.object(
        QFileDialog, "getSaveFileName", return_value=(str(tmp_path / "qr.gif"), "")
    )
    warning = mocker.patch("omr_data_collector.ui.OrganizationPage.warn")

    page.save_qr_code()

    warning.assert_called_once()


def test_print_qr_code_uses_the_page_layout_preference(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    organization = Organization(name="Food Bank", orientation="LANDSCAPE")
    save_organization(connection, organization)
    page = make_page(qtbot, connection)
    dialog_class = mocker.patch(f"{PAGE_MODULE}.QPrintDialog")
    dialog_class.return_value.exec.return_value = QDialog.DialogCode.Accepted
    paint = mocker.patch(f"{PAGE_MODULE}.paint_organization_qr_page")

    page.print_qr_code()

    printer, printed = paint.call_args.args
    assert printed == organization
    assert printer.pageLayout().orientation() == QPageLayout.Orientation.Landscape


def test_cancelling_the_print_dialog_prints_nothing(
    qtbot: QtBot, connection: sqlite3.Connection, mocker: MockerFixture
) -> None:
    save_organization(connection, Organization(name="Food Bank"))
    page = make_page(qtbot, connection)
    dialog_class = mocker.patch(f"{PAGE_MODULE}.QPrintDialog")
    dialog_class.return_value.exec.return_value = QDialog.DialogCode.Rejected
    paint = mocker.patch(f"{PAGE_MODULE}.paint_organization_qr_page")

    page.print_qr_code()

    paint.assert_not_called()


@pytest.mark.usefixtures("qapp")
def test_printed_page_carries_a_scannable_code(tmp_path: Path) -> None:
    # Paints to a PDF the way it would to a printer, then rasterizes the page with
    # Qt's PDF module and reads the code back.
    organization = Organization(name="Food Bank")
    pdf_path = tmp_path / "qr.pdf"
    writer = QPdfWriter(str(pdf_path))
    writer.setResolution(300)
    writer.setPageLayout(page_layout(organization))

    paint_organization_qr_page(writer, organization)
    del writer  # finishes the PDF

    document = QPdfDocument()
    document.load(str(pdf_path))
    page_size = document.pagePointSize(0)
    image = document.render(
        0, QSize(int(page_size.width() * 2), int(page_size.height() * 2))
    )
    image_path = tmp_path / "page.png"
    image.save(str(image_path))
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    assert image is not None
    (text,) = read_qr_codes(image)
    assert json.loads(text)["organizationId"] == organization.organization_id
