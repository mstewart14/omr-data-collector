from __future__ import annotations

import re
import uuid
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeySequence, QPixmap
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.constants import PAPER_SIZES
from omr_data_collector.i18n import tr
from omr_data_collector.identity.qr_code import (
    build_organization_payload,
    make_qr_code,
    qr_code_png,
    save_qr_code,
)
from omr_data_collector.layout.page_setup import page_layout
from omr_data_collector.models.Organization import Organization
from omr_data_collector.storage.organization_store import (
    load_organization,
    save_organization,
)
from omr_data_collector.ui.accessibility import (
    show_field_errors,
    style_error_label,
)
from omr_data_collector.ui.form_helpers import (
    add_field_row,
    add_shortcut,
    save_revert_buttons,
    warn,
)
from omr_data_collector.ui.qr_printing import paint_organization_qr_page
from omr_data_collector.ui.TablePreview import orientation_names

if TYPE_CHECKING:
    import sqlite3


def paper_size_labels() -> dict[str, str]:
    return {
        PAPER_SIZES.LETTER: tr("Letter (8.5 x 11 in)"),
        PAPER_SIZES.LEGAL: tr("Legal (8.5 x 14 in)"),
        PAPER_SIZES.A4: tr("A4 (210 x 297 mm)"),
    }


def qr_file_filters() -> dict[str, str]:
    """The Save QR code dialog's file types, and the extension of each."""
    return {
        tr("PNG image (*.png)"): ".png",
        tr("SVG image (*.svg)"): ".svg",
        tr("PDF document (*.pdf)"): ".pdf",
    }


QR_PREVIEW_SCALE = 6
ADDRESS_VISIBLE_LINES = 3


# Form rows in order: field name (as in Organization.validation_errors), label with
# its Alt+letter mnemonic after "&", and the attribute holding the input widget.
def form_fields() -> tuple[tuple[str, str, str], ...]:
    return (
        ("name", tr("Organization &name (required)"), "name_edit"),
        ("phone", tr("P&hone"), "phone_edit"),
        ("address", tr("A&ddress"), "address_edit"),
        ("url", tr("&Website"), "url_edit"),
        ("email", tr("&Email"), "email_edit"),
        ("paper_size", tr("Paper si&ze"), "paper_size_combo"),
        ("orientation", tr("&Orientation"), "orientation_combo"),
    )


class OrganizationPage(QWidget):
    """Enter, save and edit the organization's details, and get its QR code.

    Covers the "Enter Organization Data" epic on the wiki (stories 20001-20005).
    """

    status_message = Signal(str)

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__()
        self._connection = connection
        self._saved = load_organization(connection)
        # A new organization gets its permanent ID now, so it is the same from the
        # first save on.
        self._organization_id = (
            self._saved.organization_id if self._saved else uuid.uuid4().hex
        )

        layout = QHBoxLayout(self)
        layout.addWidget(self._build_details_box(), stretch=3)
        layout.addWidget(self._build_qr_box(), stretch=2)
        self._connect_signals()
        self.initial_focus: QWidget = self.name_edit

        self.revert()

    def form_organization(self) -> Organization:
        """The organization as currently entered, before normalizing."""
        return Organization(
            name=self.name_edit.text(),
            phone=self.phone_edit.text(),
            address=self.address_edit.toPlainText(),
            url=self.url_edit.text(),
            email=self.email_edit.text(),
            paper_size=self.paper_size_combo.currentData(),
            orientation=self.orientation_combo.currentData(),
            organization_id=self._organization_id,
        )

    def has_unsaved_changes(self) -> bool:
        return self.form_organization().normalized() != self._baseline()

    def save(self) -> None:
        organization = self.form_organization().normalized()
        errors = organization.validation_errors()
        if self._show_errors(errors):
            count = len(errors)
            self.status_message.emit(
                tr("%n field(s) to fix before saving.", None, count)
            )
            return

        save_organization(self._connection, organization)
        self._saved = organization
        # Show the normalized values (trimmed, https:// added) that were stored.
        self._populate(organization)
        self.status_message.emit(tr("Organization saved."))

    def revert(self) -> None:
        self._show_errors({})
        self._populate(self._baseline())

    def save_qr_code(self) -> None:
        if self._saved is None:
            return
        default_name = f"{_file_slug(self._saved.name)}-qr.png"
        file_name, selected_filter = QFileDialog.getSaveFileName(
            self, tr("Save QR code"), default_name, ";;".join(qr_file_filters())
        )
        if not file_name:
            return
        path = Path(file_name)
        if not path.suffix:
            path = path.with_suffix(qr_file_filters().get(selected_filter, ".png"))
        try:
            save_qr_code(make_qr_code(build_organization_payload(self._saved)), path)
        except (OSError, ValueError) as error:
            warn(self, tr("Couldn't save the QR code"), str(error))
            return
        self.status_message.emit(tr("QR code saved to {path}.").format(path=path))

    def print_qr_code(self) -> None:
        if self._saved is None:
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageLayout(page_layout(self._saved))
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        paint_organization_qr_page(printer, self._saved)
        self.status_message.emit(tr("QR code sent to the printer."))

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt override)
        # A theme switch (light, dark, high contrast) changes the background, so the
        # error color is chosen again to keep its contrast.
        if event.type() == QEvent.Type.PaletteChange:
            for label in self.error_labels.values():
                style_error_label(label, self.palette())
        super().changeEvent(event)

    def _build_inputs(self) -> None:
        self.name_edit = QLineEdit()
        self.phone_edit = QLineEdit()
        self.address_edit = QPlainTextEdit()
        self.address_edit.setTabChangesFocus(True)
        # Sized in lines of the current font, so it grows with the system font size.
        line_height = self.address_edit.fontMetrics().lineSpacing()
        frame = 2 * self.address_edit.frameWidth()
        margins = self.address_edit.contentsMargins()
        self.address_edit.setFixedHeight(
            line_height * ADDRESS_VISIBLE_LINES
            + frame
            + margins.top()
            + margins.bottom()
            + int(2 * self.address_edit.document().documentMargin())
        )
        self.url_edit = QLineEdit()
        self.email_edit = QLineEdit()
        self.paper_size_combo = QComboBox()
        for value, label in paper_size_labels().items():
            self.paper_size_combo.addItem(label, value)
        self.orientation_combo = QComboBox()
        for value, label in orientation_names().items():
            self.orientation_combo.addItem(label, value)

    def _build_details_box(self) -> QGroupBox:
        self._build_inputs()

        # Placeholders only give examples: they disappear once someone types, so
        # anything that must be known (like "required") is in the label instead.
        self.phone_edit.setPlaceholderText(tr("Like 613-555-0123"))
        self.address_edit.setPlaceholderText(tr("Mailing or street address"))
        self.url_edit.setPlaceholderText(tr("Like example.org"))
        self.email_edit.setPlaceholderText(tr("Like info@example.org"))

        self.field_widgets: dict[str, QWidget] = {}
        self.field_labels: dict[str, QLabel] = {}
        self.error_labels: dict[str, QLabel] = {}
        self.form = QFormLayout()
        for field_name, label_text, attribute in form_fields():
            widget = getattr(self, attribute)
            label, error_label = add_field_row(self.form, label_text, widget)
            self.field_widgets[field_name] = widget
            self.field_labels[field_name] = label
            self.error_labels[field_name] = error_label

        self.save_button, self.revert_button, buttons = save_revert_buttons(
            tr("Save the organization's details (Ctrl+S)")
        )

        details = QGroupBox(tr("Organization details"))
        details_layout = QVBoxLayout(details)
        details_layout.addLayout(self.form)
        details_layout.addStretch()
        details_layout.addLayout(buttons)
        return details

    def _build_qr_box(self) -> QGroupBox:
        self.qr_preview = QLabel()
        self.qr_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_preview.setMinimumSize(240, 240)
        self.qr_preview.setAccessibleName(tr("QR code"))
        self.qr_hint = QLabel()
        self.qr_hint.setWordWrap(True)
        self.qr_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.save_qr_button = QPushButton(tr("Sa&ve QR code…"))
        self.print_qr_button = QPushButton(tr("Pr&int QR code…"))
        qr_buttons = QHBoxLayout()
        qr_buttons.addWidget(self.save_qr_button)
        qr_buttons.addWidget(self.print_qr_button)

        qr_box = QGroupBox(tr("QR code"))
        qr_layout = QVBoxLayout(qr_box)
        qr_intro = QLabel(
            tr("Every form you create carries this code, identifying it as yours.")
        )
        qr_intro.setWordWrap(True)
        qr_layout.addWidget(qr_intro)
        qr_layout.addWidget(self.qr_preview)
        qr_layout.addWidget(self.qr_hint)
        qr_layout.addLayout(qr_buttons)
        qr_layout.addStretch()
        return qr_box

    def _connect_signals(self) -> None:
        self.save_shortcut = add_shortcut(
            self, QKeySequence.StandardKey.Save, self.save
        )

        # Tab follows the screen: the form top to bottom, its buttons left to right,
        # then the QR code's buttons.
        focus_chain = [
            *(self.field_widgets[name] for name, _, _ in form_fields()),
            self.revert_button,
            self.save_button,
            self.save_qr_button,
            self.print_qr_button,
        ]
        for before, after in pairwise(focus_chain):
            QWidget.setTabOrder(before, after)

        self.save_button.clicked.connect(self.save)
        self.revert_button.clicked.connect(self.revert)
        self.save_qr_button.clicked.connect(self.save_qr_code)
        self.print_qr_button.clicked.connect(self.print_qr_code)
        for line_edit in (
            self.name_edit,
            self.phone_edit,
            self.url_edit,
            self.email_edit,
        ):
            line_edit.textChanged.connect(self._update_state)
            line_edit.returnPressed.connect(self.save)
        self.address_edit.textChanged.connect(self._update_state)
        self.paper_size_combo.currentIndexChanged.connect(self._update_state)
        self.orientation_combo.currentIndexChanged.connect(self._update_state)

    def _baseline(self) -> Organization:
        if self._saved is not None:
            return self._saved
        return Organization(name="", organization_id=self._organization_id)

    def _populate(self, organization: Organization) -> None:
        self.name_edit.setText(organization.name)
        self.phone_edit.setText(organization.phone)
        self.address_edit.setPlainText(organization.address)
        self.url_edit.setText(organization.url)
        self.email_edit.setText(organization.email)
        self.paper_size_combo.setCurrentIndex(
            self.paper_size_combo.findData(organization.paper_size)
        )
        self.orientation_combo.setCurrentIndex(
            self.orientation_combo.findData(organization.orientation)
        )
        self._refresh_qr_preview()
        self._update_state()

    def _show_errors(self, errors: dict[str, str]) -> bool:
        """Show ``errors`` by their fields and focus the first; True if any."""
        return show_field_errors(
            self.form, self.field_widgets, self.error_labels, errors
        )

    def _update_state(self) -> None:
        unsaved = self.has_unsaved_changes()
        self.save_button.setEnabled(unsaved)
        self.revert_button.setEnabled(unsaved)

        # The code always shows what is saved, so a printed or exported code matches
        # what forms will carry.
        qr_available = self._saved is not None and not unsaved
        self.save_qr_button.setEnabled(qr_available)
        self.print_qr_button.setEnabled(qr_available)
        if self._saved is None:
            self.qr_hint.setText(tr("Save the organization to create its QR code."))
        elif unsaved:
            self.qr_hint.setText(tr("Save your changes to update the QR code."))
        else:
            self.qr_hint.setText("")

    def _refresh_qr_preview(self) -> None:
        if self._saved is None:
            self.qr_preview.clear()
            self.qr_preview.setAccessibleDescription(tr("Not created yet."))
            return
        self.qr_preview.setAccessibleDescription(
            tr(
                "Identifies {name}. Use Save QR code or Print QR code to get a copy."
            ).format(name=self._saved.name)
        )
        png = qr_code_png(
            make_qr_code(build_organization_payload(self._saved)),
            scale=QR_PREVIEW_SCALE,
        )
        pixmap = QPixmap()
        pixmap.loadFromData(png)
        self.qr_preview.setPixmap(pixmap)


def _file_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "organization"
