"""Draws a table block's grid on paper, from its layout."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen

from omr_data_collector.layout.table_layout import (
    BUBBLE_DIAMETER_MM,
    CELL_PADDING_MM,
    CHOICE_LABEL_POINT_SIZE,
    HEADER_POINT_SIZE,
    TABLE_BOX_HEIGHT_MM,
    WRITTEN_BOX_WIDTH_MM,
    cell_bubble_centres_mm,
    cell_written_marks_mm,
    heading_line_count,
    line_height_mm,
)
from omr_data_collector.layout.text import draw_text
from omr_data_collector.models.AnswerSpec import CHOICE_ANSWER_TYPES
from omr_data_collector.models.FormFont import STANDARD_SIZE

if TYPE_CHECKING:
    from PySide6.QtGui import QPainter

    from omr_data_collector.layout.table_layout import ColumnLayout, TableLayout
    from omr_data_collector.models.FormFont import FormFont
    from omr_data_collector.models.TableBlock import Column, TableBlock

INK = QColor("black")
LINE_WIDTH_MM = 0.3
# Matches the page painter's separators, a little smaller to fit a table row.
PRINTED_SEPARATOR_POINT_SIZE = 12


def paint_table(painter: QPainter, table: TableBlock, layout: TableLayout) -> None:
    """Draw the grid with its heading, at the painter's origin, in millimetres."""
    painter.save()
    painter.setPen(QPen(INK, LINE_WIDTH_MM))
    painter.setBrush(Qt.BrushStyle.NoBrush)
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
        _paint_heading(painter, column, column_layout, x, layout)
        for row in range(layout.rows):
            top = layout.header_height_mm + row * layout.row_height_mm
            _paint_cell(
                painter,
                column,
                column_layout,
                x,
                top + layout.row_height_mm / 2,
                # Printed separators fill boxes of a fixed size.
                replace(layout.font, size=STANDARD_SIZE),
            )
        x += column_layout.width_mm
    painter.restore()


def _paint_heading(
    painter: QPainter,
    column: Column,
    column_layout: ColumnLayout,
    x: float,
    layout: TableLayout,
) -> None:
    inner = column_layout.width_mm - 2 * CELL_PADDING_MM
    font = layout.font
    line = line_height_mm(HEADER_POINT_SIZE, font=font)
    for number, heading in enumerate(column_layout.heading_lines or (column.name,)):
        draw_text(
            painter,
            QRectF(x + CELL_PADDING_MM, CELL_PADDING_MM + number * line, inner, line),
            Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextSingleLine,
            heading,
            HEADER_POINT_SIZE,
            font=font,
            bold=True,
        )
    if column.example:
        # Under the headings, level across the table however many lines each has.
        top = CELL_PADDING_MM + heading_line_count(layout.columns) * line
        draw_text(
            painter,
            QRectF(x + CELL_PADDING_MM, top, inner, line),
            Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextSingleLine,
            column.example,
            HEADER_POINT_SIZE,
            font=font,
        )
    if column.answer.answer_type not in CHOICE_ANSWER_TYPES:
        return
    # Each choice's label above its bubble's column.
    label_line = line_height_mm(CHOICE_LABEL_POINT_SIZE, font=font)
    label_top = layout.header_height_mm - CELL_PADDING_MM - label_line
    pitch = inner / max(len(column.answer.printed_choices()), 1)
    for centre, choice in zip(
        cell_bubble_centres_mm(column, column_layout),
        column.answer.printed_choices(),
        strict=True,
    ):
        draw_text(
            painter,
            QRectF(x + centre - pitch / 2, label_top, pitch, label_line),
            Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextSingleLine,
            choice.label,
            CHOICE_LABEL_POINT_SIZE,
            font=font,
        )


def _paint_cell(  # noqa: PLR0913 (one cell: its column, place and font)
    painter: QPainter,
    column: Column,
    column_layout: ColumnLayout,
    x: float,
    middle: float,
    font: FormFont,
) -> None:
    for left, printed in cell_written_marks_mm(column, column_layout):
        rect = QRectF(
            x + left,
            middle - TABLE_BOX_HEIGHT_MM / 2,
            WRITTEN_BOX_WIDTH_MM,
            TABLE_BOX_HEIGHT_MM,
        )
        if printed:
            if printed.strip():
                draw_text(
                    painter,
                    rect,
                    Qt.AlignmentFlag.AlignCenter,
                    printed,
                    PRINTED_SEPARATOR_POINT_SIZE,
                    font=font,
                    bold=True,
                )
        else:
            painter.drawRect(rect)
    radius = BUBBLE_DIAMETER_MM / 2
    for centre in cell_bubble_centres_mm(column, column_layout):
        painter.drawEllipse(QPointF(x + centre, middle), radius, radius)
