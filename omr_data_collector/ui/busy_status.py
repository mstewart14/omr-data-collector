"""The status bar's sign that the app is working on something in the background.

Loading the scanning engine and checking the scanner folder go on behind the
window for seconds at a time; without a sign, nothing shows that anything is
happening. While any such work goes on, a moving bar and a few words naming it
sit at the right of the status bar; the newest work is the one named.

The bar's movement shows the work is going on, so it's part of the status, not
decoration; it stops as soon as the work does. The words are the bar's
accessible description, so a screen reader that reaches it says what it's for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, QTimer
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget

from omr_data_collector.i18n import tr

if TYPE_CHECKING:
    from PySide6.QtGui import QHideEvent, QPaintEvent, QShowEvent

# The bar's width, in characters of the status bar's text.
BAR_WIDTH_CHARACTERS = 10
# The sliding block's share of the bar, and how often it moves.
BLOCK_SHARE = 0.3
FRAME_MS = 40
# One trip across the bar, in frames: about a second and a half.
FRAMES_PER_TRIP = 36


class SweepBar(QProgressBar):
    """A progress bar with no end known, drawn as a block sliding to and fro.

    Some styles (Fusion among them) draw a busy bar as a full bar whose stripes
    barely move, which doesn't read as work going on. It stays a QProgressBar,
    so screen readers still meet a progress bar.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRange(0, 0)
        self.setTextVisible(False)
        self.frame = 0
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._advance)

    @property
    def is_moving(self) -> bool:
        return self._timer.isActive()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self._timer.stop()

    def _advance(self) -> None:
        self.frame = (self.frame + 1) % (2 * FRAMES_PER_TRIP)
        self.update()

    def block_rect(self) -> QRectF:
        """Where the sliding block is now, inside the bar's frame."""
        inside = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        block = inside.width() * BLOCK_SHARE
        # There and back: 0 to 1, then 1 to 0.
        trip = self.frame / FRAMES_PER_TRIP
        along = trip if trip <= 1 else 2 - trip
        left = inside.left() + (inside.width() - block) * along
        return QRectF(left, inside.top(), block, inside.height())

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 (Qt override)
        palette = self.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(palette.color(QPalette.ColorRole.Mid))
        painter.setBrush(palette.color(QPalette.ColorRole.Base))
        painter.drawRoundedRect(frame, 3, 3)
        painter.setPen(palette.color(QPalette.ColorRole.Highlight))
        painter.setBrush(palette.color(QPalette.ColorRole.Highlight))
        painter.drawRoundedRect(self.block_rect(), 2, 2)
        painter.end()


class BusyStatus(QWidget):
    """A moving bar and what's being done, while background work goes on."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = QLabel()
        # No end known: a block slides back and forth.
        self.bar = SweepBar()
        self.bar.setAccessibleName(tr("Working"))
        self.bar.setFixedWidth(
            self.fontMetrics().averageCharWidth() * BAR_WIDTH_CHARACTERS
        )
        self.bar.setMaximumHeight(self.fontMetrics().height())
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)
        # What's going on, by key, oldest first.
        self._work: dict[str, str] = {}
        self.hide()

    def begin(self, key: str, text: str) -> None:
        """Show that ``text`` is being done, until ``end(key)``."""
        self._work.pop(key, None)
        self._work[key] = text
        self._show_latest()

    def end(self, key: str) -> None:
        """That work is done; the sign goes when no work is left."""
        self._work.pop(key, None)
        self._show_latest()

    @property
    def text(self) -> str:
        """What's being done, as shown; "" when nothing is."""
        return self.label.text() if self._work else ""

    def _show_latest(self) -> None:
        if not self._work:
            self.hide()
            return
        text = list(self._work.values())[-1]
        self.label.setText(text)
        self.bar.setAccessibleDescription(text)
        self.show()
