from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from omr_data_collector.constants import ANSWER_TYPES, PAGE_ORIENTATIONS, PAPER_SIZES
from omr_data_collector.layout.table_layout import (
    BUBBLE_DIAMETER_MM,
    CELL_PADDING_MM,
    CHOICE_LABEL_POINT_SIZE,
    HEADER_POINT_SIZE,
    MM_PER_POINT,
    WRITTEN_BOX_WIDTH_MM,
    line_height_mm,
    rows_to_print,
    table_layout,
)
from omr_data_collector.ui.page_setup import (
    PAGE_MARGIN_MM,
    page_layout_for,
    printable_size_mm,
)

if TYPE_CHECKING:
    from PySide6.QtGui import QPaintEvent

    from omr_data_collector.layout.table_layout import ColumnLayout, TableLayout
    from omr_data_collector.models.TableBlock import Column, TableBlock

PAPER_SIZE_NAMES = {
    PAPER_SIZES.LETTER: "Letter",
    PAPER_SIZES.LEGAL: "Legal",
    PAPER_SIZES.A4: "A4",
}
ORIENTATION_NAMES = {
    PAGE_ORIENTATIONS.PORTRAIT: "portrait",
    PAGE_ORIENTATIONS.LANDSCAPE: "landscape",
}
PREVIEW_MIN_SIZE = QSize(300, 380)
WRITTEN_BOX_HEIGHT_MM = 6.0


def fit_summary(table: TableBlock, paper_size: str, orientation: str) -> str:
    """Says in words what the preview shows: whether the table fits the page."""
    page = f"{PAPER_SIZE_NAMES[paper_size]} {ORIENTATION_NAMES[orientation]}"
    if not table.columns:
        return f"Add columns to preview the table on {page}."
    layout = table_layout(table)
    printable_width, printable_height = printable_size_mm(paper_size, orientation)
    width = round(layout.width_mm)
    room = round(printable_width)
    if layout.width_mm > printable_width:
        sentence = (
            f"Too wide for {page}: the table is {width} mm wide and the page has "
            f"{room} mm. Try landscape, fewer columns, or fewer or shorter choices."
        )
    else:
        sentence = f"Fits on {page}: {width} of {room} mm wide."
    per_page = layout.rows_per_page(printable_height)
    if table.fill_page:
        sentence += (
            f" Fills the page: {per_page} rows on {page} when the table starts at the "
            "top of a page; fewer if it's placed lower on a form."
        )
    elif 0 < per_page < table.rows:
        pages = -(-table.rows // per_page)
        sentence += f" {per_page} rows fit on a page, so the table takes {pages} pages."
    return sentence


class TablePreview(QWidget):
    """A table block drawn to scale on a page, with margins, for checking fit."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(PREVIEW_MIN_SIZE)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Table preview")
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
                _paint_table(painter, self._table, replace(layout, rows=shown))
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


def _font(point_size: float, *, bold: bool = False) -> QFont:
    """A font sized in millimetres, matching the painter's millimetre scale."""
    font = QFont()
    font.setPixelSize(max(round(point_size * MM_PER_POINT * 10), 1))
    font.setBold(bold)
    return font


def _paint_table(painter: QPainter, table: TableBlock, layout: TableLayout) -> None:
    ink = QColor("black")
    painter.setPen(QPen(ink, 0.3))
    width, height = layout.width_mm, layout.height_mm
    painter.drawRect(QRectF(0, 0, width, height))
    painter.drawLine(
        QPointF(0, layout.header_height_mm), QPointF(width, layout.header_height_mm)
    )
    for row in range(1, layout.rows):
        y = layout.header_height_mm + row * layout.row_height_mm
        painter.drawLine(QPointF(0, y), QPointF(width, y))

    x = 0.0
    for column, column_layout in zip(table.columns, layout.columns, strict=True):
        if x:
            painter.drawLine(QPointF(x, 0), QPointF(x, height))
        _paint_heading(painter, column, x, column_layout.width_mm, layout)
        for row in range(layout.rows):
            top = layout.header_height_mm + row * layout.row_height_mm
            _paint_cell(painter, column, x, top, column_layout, layout)
        x += column_layout.width_mm


def _paint_heading(
    painter: QPainter, column: Column, x: float, width: float, layout: TableLayout
) -> None:
    # Text is drawn at 10x size, then scaled down, because fonts can't be smaller
    # than a pixel and the painter's units here are millimetres.
    painter.save()
    painter.translate(x + CELL_PADDING_MM, CELL_PADDING_MM)
    painter.scale(0.1, 0.1)
    text_width = (width - 2 * CELL_PADDING_MM) * 10
    line = line_height_mm(HEADER_POINT_SIZE) * 10
    painter.setFont(_font(HEADER_POINT_SIZE, bold=True))
    painter.drawText(
        QRectF(0, 0, text_width, line), Qt.AlignmentFlag.AlignLeft, column.name
    )
    y = line
    if column.example:
        painter.setFont(_font(HEADER_POINT_SIZE))
        painter.drawText(
            QRectF(0, y, text_width, line),
            Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextSingleLine,
            column.example,
        )
    painter.restore()

    pitch = 0.0
    if column.answer.answer_type != ANSWER_TYPES.WRITTEN:
        pitch = (width - 2 * CELL_PADDING_MM) / max(len(column.answer.choices), 1)
        label_top = (
            layout.header_height_mm
            - CELL_PADDING_MM
            - line_height_mm(CHOICE_LABEL_POINT_SIZE)
        )
        painter.save()
        painter.scale(0.1, 0.1)
        painter.setFont(_font(CHOICE_LABEL_POINT_SIZE))
        for index, choice in enumerate(column.answer.choices):
            left = x + CELL_PADDING_MM + index * pitch
            painter.drawText(
                QRectF(
                    left * 10,
                    label_top * 10,
                    pitch * 10,
                    line_height_mm(CHOICE_LABEL_POINT_SIZE) * 10,
                ),
                Qt.AlignmentFlag.AlignHCenter,
                choice.label,
            )
        painter.restore()


def _paint_cell(  # noqa: PLR0913 (a cell's position and both layouts)
    painter: QPainter,
    column: Column,
    x: float,
    top: float,
    column_layout: ColumnLayout,
    layout: TableLayout,
) -> None:
    middle = top + layout.row_height_mm / 2
    inner = column_layout.width_mm - 2 * CELL_PADDING_MM
    if column.answer.answer_type == ANSWER_TYPES.WRITTEN:
        boxes = column.answer.characters()
        left = x + CELL_PADDING_MM + (inner - boxes * WRITTEN_BOX_WIDTH_MM) / 2
        for box in range(boxes):
            painter.drawRect(
                QRectF(
                    left + box * WRITTEN_BOX_WIDTH_MM,
                    middle - WRITTEN_BOX_HEIGHT_MM / 2,
                    WRITTEN_BOX_WIDTH_MM,
                    WRITTEN_BOX_HEIGHT_MM,
                )
            )
        return
    count = max(len(column.answer.choices), 1)
    pitch = inner / count
    radius = BUBBLE_DIAMETER_MM / 2
    for index in range(len(column.answer.choices)):
        centre = QPointF(x + CELL_PADDING_MM + (index + 0.5) * pitch, middle)
        painter.drawEllipse(centre, radius, radius)
