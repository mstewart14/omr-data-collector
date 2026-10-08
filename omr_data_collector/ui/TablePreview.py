from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from omr_data_collector.constants import PAGE_ORIENTATIONS, PAPER_SIZES
from omr_data_collector.i18n import tr
from omr_data_collector.layout.page_setup import (
    PAGE_MARGIN_MM,
    page_layout_for,
    printable_size_mm,
)
from omr_data_collector.layout.table_layout import (
    rows_to_print,
    table_layout,
)
from omr_data_collector.rendering.table_painter import paint_table

if TYPE_CHECKING:
    from PySide6.QtGui import QPaintEvent

    from omr_data_collector.models.TableBlock import TableBlock

PREVIEW_MIN_SIZE = QSize(300, 380)


def fit_summary(table: TableBlock, paper_size: str, orientation: str) -> str:
    """Says in words what the preview shows: whether the table fits the page."""
    page = page_name(paper_size, orientation)
    if not table.columns:
        return tr("Add columns to preview the table on {page}.").format(page=page)
    layout = table_layout(table)
    printable_width, printable_height = printable_size_mm(paper_size, orientation)
    width = round(layout.width_mm)
    room = round(printable_width)
    if layout.width_mm > printable_width:
        sentences = [
            tr(
                "Too wide for {page}: the table is {width} mm wide and the page has "
                "{room} mm. Try landscape, fewer columns, or fewer or shorter choices."
            ).format(page=page, width=width, room=room)
        ]
    else:
        sentences = [
            tr("Fits on {page}: {width} of {room} mm wide.").format(
                page=page, width=width, room=room
            )
        ]
    per_page = layout.rows_per_page(printable_height)
    if table.fill_page:
        sentences.append(
            tr(
                "Fills the page: %n row(s) on {page} when the table starts at the "
                "top of a page; fewer if it's placed lower on a form.",
                None,
                per_page,
            ).format(page=page)
        )
    elif 0 < per_page < table.rows:
        pages = -(-table.rows // per_page)
        # Two counts, so two sentences: each gets its own plural form.
        sentences.append(tr("%n row(s) fit on a page,", None, per_page))
        sentences.append(tr("so the table takes %n page(s).", None, pages))
    return " ".join(sentences)


def orientation_names() -> dict[str, str]:
    """Each page orientation's name, for lists to choose from."""
    return {
        PAGE_ORIENTATIONS.PORTRAIT: tr("Portrait"),
        PAGE_ORIENTATIONS.LANDSCAPE: tr("Landscape"),
    }


def page_name(paper_size: str, orientation: str) -> str:
    """A page's paper and orientation, like "Letter portrait"."""
    portrait = orientation == PAGE_ORIENTATIONS.PORTRAIT
    names = {
        PAPER_SIZES.LETTER: (tr("Letter portrait"), tr("Letter landscape")),
        PAPER_SIZES.LEGAL: (tr("Legal portrait"), tr("Legal landscape")),
        PAPER_SIZES.A4: (tr("A4 portrait"), tr("A4 landscape")),
    }
    return names[paper_size][0 if portrait else 1]


class TablePreview(QWidget):
    """A table block drawn to scale on a page, with margins, for checking fit."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(PREVIEW_MIN_SIZE)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(tr("Table preview"))
        self._table: TableBlock | None = None
        self._paper_size = PAPER_SIZES.LETTER
        self._orientation = PAGE_ORIENTATIONS.PORTRAIT

    def set_table(self, table: TableBlock, paper_size: str, orientation: str) -> None:
        self._table = table
        self._paper_size = paper_size
        self._orientation = orientation
        # The drawing can't be read by a screen reader; the summary says the same.
        self.setAccessibleDescription(fit_summary(table, paper_size, orientation))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt override)
        del event
        page = page_layout_for(self._paper_size, self._orientation)
        page_size = page.fullRect(page.Unit.Millimeter)
        scale = min(
            (self.width() - 2) / page_size.width(),
            (self.height() - 2) / page_size.height(),
        )
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.translate(
                (self.width() - page_size.width() * scale) / 2,
                (self.height() - page_size.height() * scale) / 2,
            )
            painter.scale(scale, scale)
            self._paint_page(painter, page_size.width(), page_size.height())
            if self._table is not None and self._table.columns:
                painter.translate(PAGE_MARGIN_MM, PAGE_MARGIN_MM)
                layout = table_layout(self._table)
                # The first page only: rows that don't fit continue on the next
                # page, as the summary says.
                _, printable_height = printable_size_mm(
                    self._paper_size, self._orientation
                )
                # A table that fills its page is previewed from the top of one.
                rows = rows_to_print(self._table, printable_height)
                shown = min(rows, layout.rows_per_page(printable_height))
                paint_table(painter, self._table, replace(layout, rows=shown))
        finally:
            painter.end()

    def _paint_page(self, painter: QPainter, width: float, height: float) -> None:
        # Paper is drawn white on any theme: it previews print, not the screen.
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Mid), 0))
        painter.setBrush(QColor("white"))
        painter.drawRect(QRectF(0, 0, width, height))
        margin = QPen(QColor("#9aa0a6"), 0, Qt.PenStyle.DashLine)
        painter.setPen(margin)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(
            QRectF(
                PAGE_MARGIN_MM,
                PAGE_MARGIN_MM,
                width - 2 * PAGE_MARGIN_MM,
                height - 2 * PAGE_MARGIN_MM,
            )
        )
