from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from omr_data_collector import APP_NAME, ISSUES_URL, REPOSITORY_URL, app_version
from omr_data_collector.i18n import tr
from omr_data_collector.ui.app_icon import app_icon

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

ICON_SIZE = 64


def _link(url: str, text: str) -> str:
    return f'<a href="{escape(url)}">{escape(text)}</a>'


class AboutDialog(QDialog):
    """Preferences > About: the app's version, its source code and where to report problems.

    The links open in the web browser, and are reached with Tab and opened with
    Enter like any other control.
    """

    def __init__(self, parent: QWidget | None, version: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("About {app}").format(app=APP_NAME))
        version = app_version() if version is None else version

        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(ICON_SIZE, ICON_SIZE))
        icon.setAccessibleName(tr("App icon"))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label = QLabel(APP_NAME)
        font = self.name_label.font()
        font.setPointSizeF(font.pointSizeF() * 1.4)
        font.setBold(True)
        self.name_label.setFont(font)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label = QLabel(
            tr("Version {version}").format(version=version)
            if version
            else tr("Version unknown")
        )
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.source_link = self._link_label(REPOSITORY_URL, tr("Source code on GitHub"))
        self.issues_link = self._link_label(
            ISSUES_URL, tr("Report a problem or suggest an idea")
        )

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(icon)
        layout.addWidget(self.name_label)
        layout.addWidget(self.version_label)
        layout.addSpacing(self.fontMetrics().height() // 2)
        layout.addWidget(self.source_link)
        layout.addWidget(self.issues_link)
        layout.addWidget(self.buttons)
        self.setTabOrder(self.source_link, self.issues_link)
        self.setTabOrder(self.issues_link, self.buttons)
        self.source_link.setFocus(Qt.FocusReason.OtherFocusReason)

    def _link_label(self, url: str, text: str) -> QLabel:
        label = QLabel(_link(url, text))
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setOpenExternalLinks(True)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )
        label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setAccessibleName(text)
        label.setAccessibleDescription(url)
        label.setToolTip(url)
        return label
