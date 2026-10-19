from __future__ import annotations

from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.i18n import tr
from omr_data_collector.ui.app_font import TEXT_SIZES, desktop_text_font
from omr_data_collector.ui.form_helpers import add_field_row, ok_cancel_buttons


def points(size: float) -> str:
    """A size in points, as this language writes numbers ("10.5 pt")."""
    return tr("{size} pt").format(size=QLocale().toString(float(size), "g", 4))


class TextSizeDialog(QDialog):
    """Choose the size of the app's own text (Preferences > Text size).

    "Same as the desktop" follows the desktop's font setting. Printed forms aren't
    affected: each form sets its own text size.
    """

    def __init__(self, parent: QWidget | None, current: float) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Text size"))
        self.size_combo = QComboBox()
        desktop = desktop_text_font().pointSizeF()
        if desktop > 0:
            same = tr("Same as the desktop ({size})").format(size=points(desktop))
        else:
            same = tr("Same as the desktop")
        self.size_combo.addItem(same, 0.0)
        sizes = sorted({*TEXT_SIZES, current} - {0})
        for size in sizes:
            self.size_combo.addItem(points(size), float(size))
        self.size_combo.setCurrentIndex(
            max(self.size_combo.findData(float(current)), 0)
        )
        form = QFormLayout()
        add_field_row(form, tr("Text &size"), self.size_combo)
        note = QLabel(
            tr(
                "Changes the text in the app's windows straight away. Printed "
                "forms keep the text size set in each form's details."
            )
        )
        note.setWordWrap(True)

        self.buttons = ok_cancel_buttons(self)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(self.buttons)
        self.size_combo.setFocus(Qt.FocusReason.OtherFocusReason)

    def chosen_size(self) -> float:
        """The chosen size in points, or 0 for the desktop's."""
        return self.size_combo.currentData()
