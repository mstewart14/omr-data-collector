from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from omr_data_collector.i18n import tr

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtGui import QPaintEvent

# The outline round the answer being checked: thick and in a strong color, since
# it has to stand out on a page of black print and pencil marks.
HIGHLIGHT_COLOR = QColor("#0b57d0")
HIGHLIGHT_WIDTH_PX = 3
# Room round a close-up so the writing isn't cut off at the edges of its box.
CLOSE_UP_MARGIN_PX = 12
MIN_VIEW_SIZE = QSize(260, 340)


class PageImageView(QWidget):
    """A captured sheet's image, fitted to the space, with one region outlined.

    The image is the page straightened when it was read, at template scale, so
    an ``AnswerRegion.rect`` outlines its answer; before a sheet is read (or if
    it couldn't be) the photo itself is shown, with nothing outlined.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(MIN_VIEW_SIZE)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(tr("Sheet image"))
        self._pixmap = QPixmap()
        self._highlight: QRect | None = None

    def show_image(self, path: Path | None, description: str) -> None:
        self._pixmap = QPixmap(str(path)) if path is not None else QPixmap()
        self._highlight = None
        self.setAccessibleDescription(description)
        self.update()

    def has_image(self) -> bool:
        return not self._pixmap.isNull()

    def highlight(self, rect: tuple[int, int, int, int] | None) -> None:
        self._highlight = QRect(*rect) if rect is not None else None
        self.update()

    def close_up(self, rect: tuple[int, int, int, int]) -> QPixmap:
        """The part of the image in ``rect``, with a little margin round it."""
        if self._pixmap.isNull():
            return QPixmap()
        area = QRect(*rect).adjusted(
            -CLOSE_UP_MARGIN_PX,
            -CLOSE_UP_MARGIN_PX,
            CLOSE_UP_MARGIN_PX,
            CLOSE_UP_MARGIN_PX,
        )
        return self._pixmap.copy(area.intersected(self._pixmap.rect()))

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        if self._pixmap.isNull():
            painter.setPen(self.palette().text().color())
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                tr("Choose a sheet to see it here."),
            )
            return
        target = self._target_rect()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
        if self._highlight is not None:
            scale = target.width() / self._pixmap.width()
            outline = QRectF(
                target.x() + self._highlight.x() * scale,
                target.y() + self._highlight.y() * scale,
                self._highlight.width() * scale,
                self._highlight.height() * scale,
            )
            painter.setPen(QPen(HIGHLIGHT_COLOR, HIGHLIGHT_WIDTH_PX))
            painter.drawRect(outline)

    def _target_rect(self) -> QRectF:
        """Where the image goes: as big as fits, keeping its shape, centred."""
        size = self._pixmap.size().scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio
        )
        x = (self.width() - size.width()) / 2
        y = (self.height() - size.height()) / 2
        return QRectF(x, y, size.width(), size.height())
