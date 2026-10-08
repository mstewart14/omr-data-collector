from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.i18n import language_choices, tr
from omr_data_collector.ui.form_helpers import add_field_row

if TYPE_CHECKING:
    from collections.abc import Sequence


class LanguageDialog(QDialog):
    """Choose the app's language (Preferences > Language).

    "System language" follows the desktop's language setting; a language the
    app has no translation for shows in English.
    """

    def __init__(
        self,
        parent: QWidget | None,
        current: str,
        choices: Sequence[tuple[str, str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Language"))
        self.language_combo = QComboBox()
        for code, name in choices if choices is not None else language_choices():
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(
            max(self.language_combo.findData(current), 0)
        )
        form = QFormLayout()
        add_field_row(form, tr("&Language"), self.language_combo)
        note = QLabel(tr("The app changes language the next time it starts."))
        note.setWordWrap(True)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(self.buttons)
        self.language_combo.setFocus(Qt.FocusReason.OtherFocusReason)

    def chosen_language(self) -> str:
        """The chosen language's code, or "" for the system's."""
        return self.language_combo.currentData()
