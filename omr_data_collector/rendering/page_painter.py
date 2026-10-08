"""Draws a form's pages from their layout: for the editor now, for printing later.

The painter works in millimetres with its origin at the top-left of the
printable area. It draws only what goes on paper; the editor adds its own
selection and drop markers on top.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from omr_data_collector.identity.qr_code import (
    build_form_payload,
    make_qr_code,
    qr_code_png,
)
from omr_data_collector.layout.form_layout import (
    ANSWER_LABEL_POINT_SIZE,
    ANSWER_ROW_HEIGHT_MM,
    BODY_POINT_SIZE,
    BUBBLE_LABEL_GAP_MM,
    EXAMPLE_POINT_SIZE,
    HEADER_HEIGHT_MM,
    QR_SIZE_MM,
)
from omr_data_collector.layout.markers import MARKER_DIAMETER_MM, marker_centres_mm
from omr_data_collector.layout.table_layout import BUBBLE_DIAMETER_MM
from omr_data_collector.layout.text import (
    draw_document,
    draw_text,
    line_height_mm,
    markdown_document,
    plain_document,
)
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TableBlock import TableBlock
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.rendering.table_painter import paint_table

if TYPE_CHECKING:
    from omr_data_collector.layout.form_layout import (
        FormLayout,
        PageLayout,
        PlacedBlock,
    )
    from omr_data_collector.models.Form import Form
    from omr_data_collector.models.Organization import Organization

INK = QColor("black")
MUTED_INK = QColor("#5f6368")
LINE_WIDTH_MM = 0.3
ORGANIZATION_POINT_SIZE = 12
FORM_NAME_POINT_SIZE = 11
DETAIL_POINT_SIZE = 8
HEADER_TEXT_GAP_MM = 4.0
# Large and bold, so the separators read clearly between the boxes.
PRINTED_SEPARATOR_POINT_SIZE = 14


def paint_page(
    painter: QPainter,
    form: Form,
    organization: Organization | None,
    layout: FormLayout,
    page: PageLayout,
) -> None:
    """Draw one page: its corner markers, its header, then its blocks."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    _paint_markers(painter, layout)
    _paint_header(painter, form, organization, layout, page)
    for placed in page.blocks:
        painter.save()
        painter.translate(0, placed.y_mm)
        _paint_block(painter, placed, layout.width_mm)
        painter.restore()
    painter.restore()


def _paint_markers(painter: QPainter, layout: FormLayout) -> None:
    """The four registration markers, in the margins (negative coordinates)."""
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(INK)
    radius = MARKER_DIAMETER_MM / 2
    for x, y in marker_centres_mm(layout.paper_width_mm, layout.paper_height_mm):
        painter.drawEllipse(QPointF(x, y), radius, radius)
    painter.restore()


def _paint_header(
    painter: QPainter,
    form: Form,
    organization: Organization | None,
    layout: FormLayout,
    page: PageLayout,
) -> None:
    width = layout.width_mm
    qr = QRectF(width - QR_SIZE_MM, 0, QR_SIZE_MM, QR_SIZE_MM)
    if organization is not None:
        payload = build_form_payload(
            organization.organization_id,
            form.form_id,
            max(form.version, 1),
            page.number,
        )
        image = QImage.fromData(qr_code_png(make_qr_code(payload), scale=1))
        # One pixel per module, scaled up without smoothing: sharp at any size.
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, on=False)
        painter.drawImage(qr, image)
        painter.restore()
    else:
        painter.setPen(QPen(MUTED_INK, LINE_WIDTH_MM, Qt.PenStyle.DashLine))
        painter.drawRect(qr)
        painter.setPen(QPen(MUTED_INK))
        draw_text(
            painter, qr, Qt.AlignmentFlag.AlignCenter, "QR code", DETAIL_POINT_SIZE
        )

    text_width = width - QR_SIZE_MM - HEADER_TEXT_GAP_MM
    y = 0.0

    def line(
        text: str, point_size: float, *, bold: bool = False, muted: bool = False
    ) -> None:
        nonlocal y
        height = line_height_mm(point_size)
        painter.setPen(QPen(MUTED_INK if muted else INK))
        draw_text(
            painter,
            QRectF(0, y, text_width, height),
            Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextSingleLine,
            text,
            point_size,
            bold=bold,
        )
        y += height

    if organization is not None:
        line(organization.name, ORGANIZATION_POINT_SIZE, bold=True)
        contact = " · ".join(
            part
            for part in (organization.phone, organization.email, organization.url)
            if part
        )
        if contact:
            line(contact, DETAIL_POINT_SIZE)
        if organization.address:
            line(", ".join(organization.address.splitlines()), DETAIL_POINT_SIZE)
    else:
        line(
            "Organization details not entered yet", ORGANIZATION_POINT_SIZE, muted=True
        )
    y += 1.0
    line(form.name or "Untitled form", FORM_NAME_POINT_SIZE, bold=True)
    version = f"Version {form.version}" if form.version else "Not saved yet"
    line(
        f"{version} · Page {page.number} of {len(layout.pages)}",
        DETAIL_POINT_SIZE,
        muted=True,
    )

    painter.setPen(QPen(INK, LINE_WIDTH_MM))
    rule = HEADER_HEIGHT_MM - LINE_WIDTH_MM
    painter.drawLine(QPointF(0, rule), QPointF(width, rule))


def _paint_block(painter: QPainter, placed: PlacedBlock, width: float) -> None:
    content = placed.block.content
    painter.setPen(QPen(INK, LINE_WIDTH_MM))
    if isinstance(content, TextBlock):
        draw_document(
            painter, markdown_document(content.content, width, BODY_POINT_SIZE), 0, 0
        )
    elif isinstance(content, Question) and placed.question is not None:
        _paint_question(painter, content, placed, width)
    elif isinstance(content, TableBlock) and placed.table_part is not None:
        part = placed.table_part
        if part.instructions_height_mm:
            draw_document(
                painter,
                markdown_document(content.instructions, width, BODY_POINT_SIZE),
                0,
                0,
            )
        painter.save()
        painter.translate(0, part.grid_top_mm)
        paint_table(painter, content, part.layout)
        painter.restore()


def _paint_question(
    painter: QPainter, question: Question, placed: PlacedBlock, width: float
) -> None:
    geometry = placed.question
    assert geometry is not None  # noqa: S101 (checked by the caller)
    draw_document(
        painter, markdown_document(question.prompt, width, BODY_POINT_SIZE), 0, 0
    )
    if question.example:
        painter.setPen(QPen(MUTED_INK))
        draw_document(
            painter,
            plain_document(question.example, width, EXAMPLE_POINT_SIZE, italic=True),
            0,
            geometry.example_top_mm,
        )
    painter.setPen(QPen(INK, LINE_WIDTH_MM))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    radius = BUBBLE_DIAMETER_MM / 2
    for bubble in geometry.bubbles:
        painter.drawEllipse(
            QPointF(bubble.centre_x_mm, bubble.centre_y_mm), radius, radius
        )
        label_left = bubble.centre_x_mm + radius + BUBBLE_LABEL_GAP_MM
        draw_text(
            painter,
            QRectF(
                label_left,
                bubble.centre_y_mm - ANSWER_ROW_HEIGHT_MM / 2,
                width - label_left,
                ANSWER_ROW_HEIGHT_MM,
            ),
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter
            | Qt.TextFlag.TextSingleLine,
            bubble.label,
            ANSWER_LABEL_POINT_SIZE,
        )
    for box in geometry.boxes:
        rect = QRectF(box.x_mm, box.y_mm, box.width_mm, box.height_mm)
        if box.printed:
            draw_printed_character(painter, rect, box.printed)
        else:
            painter.drawRect(rect)
    for line in geometry.lines:
        painter.drawLine(
            QPointF(line.x_mm, line.y_mm), QPointF(line.x_mm + line.width_mm, line.y_mm)
        )


def draw_printed_character(painter: QPainter, rect: QRectF, character: str) -> None:
    """A separator printed in a box's place: the / of a date or : of a time."""
    if character.strip():
        draw_text(
            painter,
            rect,
            Qt.AlignmentFlag.AlignCenter,
            character,
            PRINTED_SEPARATOR_POINT_SIZE,
            bold=True,
        )
