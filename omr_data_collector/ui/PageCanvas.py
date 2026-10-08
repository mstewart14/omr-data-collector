from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from omr_data_collector.constants import PAPER_SIZES
from omr_data_collector.layout.form_layout import layout_form
from omr_data_collector.layout.page_setup import PAGE_MARGIN_MM, page_layout_for
from omr_data_collector.rendering.page_painter import paint_page

if TYPE_CHECKING:
    from collections.abc import Iterable

    from PySide6.QtGui import (
        QDragEnterEvent,
        QDragLeaveEvent,
        QDragMoveEvent,
        QDropEvent,
        QKeyEvent,
        QMouseEvent,
        QPaintEvent,
        QResizeEvent,
    )

    from omr_data_collector.layout.form_layout import FormLayout
    from omr_data_collector.models.Form import Form
    from omr_data_collector.models.Organization import Organization

# A block from a library palette (kind and ID), or a block already on the form
# (its index), being dragged.
LIBRARY_BLOCK_MIME = "application/x-omr-data-collector-library-block"
FORM_BLOCK_MIME = "application/x-omr-data-collector-form-block"
PAGE_GAP_PX = 24
SIDE_PADDING_PX = 24
MIN_SCALE = 1.5  # pixels per millimetre
MAX_SCALE = 5.0
SELECTION_PEN_PX = 2
DROP_LINE_PX = 3


@dataclass(frozen=True)
class _BlockArea:
    """Where one placed block (or table part) is drawn, in widget pixels."""

    index: int
    rect: QRectF


class PageCanvas(QWidget):
    """The form's pages drawn as they will print, for arranging blocks by mouse.

    Blocks are picked by clicking, moved by dragging, and added by dropping
    blocks from a library palette. Everything here can also be done from the
    page's Outline list and buttons, for keyboard and screen-reader users.
    """

    # A block clicked (-1 for empty paper), and whether Ctrl (toggle it in the
    # selection) or Shift (extend the selection to it) was held.
    selection_requested = Signal(int, bool, bool)
    block_activated = Signal(int)
    # A library block's kind and ID, and where it was dropped (an insert index).
    library_block_dropped = Signal(str, str, int)
    # The indices of the blocks dragged, and the insert index they were dropped at.
    blocks_moved = Signal(list, int)
    # Delete or Backspace pressed while the pages have focus.
    delete_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setAccessibleName("Form pages")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Takes focus when clicked, so Delete works on what was clicked, but isn't
        # a Tab stop: the Outline list does the same things from the keyboard.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._form: Form | None = None
        self._organization: Organization | None = None
        self._paper_size = PAPER_SIZES.LETTER
        self._layout: FormLayout | None = None
        self._areas: list[_BlockArea] = []
        self.selected_indices: set[int] = set()
        self.drop_index: int | None = None
        self._press_position: QPoint | None = None
        self._press_index = -1
        self._narrow_on_release = False

    @property
    def form_layout(self) -> FormLayout | None:
        return self._layout

    def set_form(
        self, form: Form, organization: Organization | None, paper_size: str
    ) -> None:
        self._form = form
        self._organization = organization
        self._paper_size = paper_size
        self._layout = layout_form(form, paper_size)
        self.setAccessibleDescription(self.summary())
        self._relayout()

    def select(self, indices: Iterable[int]) -> None:
        self.selected_indices = set(indices)
        self.update()

    def summary(self) -> str:
        """The pages in words, for screen readers: what is on each page."""
        if self._layout is None or self._form is None:
            return ""
        pages = []
        for page in self._layout.pages:
            names = []
            for placed in page.blocks:
                name = placed.block.content.name
                part = placed.table_part
                if part is not None:
                    last = part.first_row + part.row_count
                    name += f" (rows {part.first_row + 1} to {last})"
                names.append(name)
            pages.append(f"Page {page.number}: {', '.join(names) or 'empty'}.")
        count = len(self._layout.pages)
        return f"{count} page{'s' if count != 1 else ''}. " + " ".join(pages)

    # --- Geometry -----------------------------------------------------------------

    def _page_size_mm(self) -> tuple[float, float]:
        orientation = self._form.orientation if self._form else "PORTRAIT"
        layout = page_layout_for(self._paper_size, orientation)
        rect = layout.fullRect(layout.Unit.Millimeter)
        return rect.width(), rect.height()

    def _scale(self) -> float:
        page_width, _ = self._page_size_mm()
        available = max(self.width() - 2 * SIDE_PADDING_PX, 1)
        return min(max(available / page_width, MIN_SCALE), MAX_SCALE)

    def _page_origin(self, page_index: int) -> QPointF:
        page_width, page_height = self._page_size_mm()
        scale = self._scale()
        x = (self.width() - page_width * scale) / 2
        y = PAGE_GAP_PX + page_index * (page_height * scale + PAGE_GAP_PX)
        return QPointF(max(x, SIDE_PADDING_PX / 2), y)

    def _relayout(self) -> None:
        self._areas = []
        if self._layout is None:
            return
        scale = self._scale()
        for page_index, page in enumerate(self._layout.pages):
            origin = self._page_origin(page_index)
            for placed in page.blocks:
                self._areas.append(
                    _BlockArea(
                        placed.index,
                        QRectF(
                            origin.x() + PAGE_MARGIN_MM * scale,
                            origin.y() + (PAGE_MARGIN_MM + placed.y_mm) * scale,
                            self._layout.width_mm * scale,
                            placed.height_mm * scale,
                        ),
                    )
                )
        _, page_height = self._page_size_mm()
        pages = len(self._layout.pages)
        self.setFixedHeight(
            int(PAGE_GAP_PX + pages * (page_height * scale + PAGE_GAP_PX))
        )
        self.update()

    def block_at(self, position: QPointF) -> int:
        """The index of the block drawn at ``position``, or -1."""
        for area in self._areas:
            if area.rect.contains(position):
                return area.index
        return -1

    def insert_index_at(self, position: QPointF) -> int:
        """Where a block dropped at ``position`` is inserted.

        Before the first block whose middle is below it, or at the end.
        """
        for area in self._areas:
            same_page_or_later = area.rect.bottom() >= position.y() - PAGE_GAP_PX
            if same_page_or_later and position.y() < area.rect.center().y():
                return area.index
        return len(self._form.blocks) if self._form else 0

    def _drop_line_y(self, index: int) -> float | None:
        before = [area for area in self._areas if area.index == index]
        if before:
            return before[0].rect.top() - 2
        if self._areas:
            return self._areas[-1].rect.bottom() + 2
        return None

    # --- Painting -----------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._relayout()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt override)
        del event
        if self._layout is None or self._form is None:
            return
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.Dark))
            page_width, page_height = self._page_size_mm()
            scale = self._scale()
            for page_index, page in enumerate(self._layout.pages):
                origin = self._page_origin(page_index)
                painter.save()
                painter.translate(origin)
                painter.scale(scale, scale)
                # Paper is white on any theme: it previews print, not the screen.
                painter.fillRect(QRectF(0, 0, page_width, page_height), QColor("white"))
                painter.translate(PAGE_MARGIN_MM, PAGE_MARGIN_MM)
                paint_page(painter, self._form, self._organization, self._layout, page)
                painter.restore()
            self._paint_markers(painter)
        finally:
            painter.end()

    def _paint_markers(self, painter: QPainter) -> None:
        highlight = self.palette().color(QPalette.ColorRole.Highlight)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.selected_indices:
            painter.setPen(QPen(highlight, SELECTION_PEN_PX))
            for area in self._areas:
                if area.index in self.selected_indices:
                    painter.drawRect(area.rect.adjusted(-3, -3, 3, 3))
        if self.drop_index is not None:
            y = self._drop_line_y(self.drop_index)
            if y is not None and self._layout is not None:
                left = self._areas[0].rect.left() if self._areas else SIDE_PADDING_PX
                width = self._layout.width_mm * self._scale()
                painter.setPen(QPen(highlight, DROP_LINE_PX))
                painter.drawLine(QPointF(left, y), QPointF(left + width, y))

    # --- Mouse and drag-and-drop --------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = event.position().toPoint()
            self._press_index = self.block_at(event.position())
            modifiers = event.modifiers()
            toggle = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
            extend = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
            # A plain press on an already selected block keeps the selection, so
            # the whole group can be dragged; it narrows on release instead.
            already_selected = self._press_index in self.selected_indices
            if toggle or extend or not already_selected:
                self.selection_requested.emit(self._press_index, toggle, extend)
                self._narrow_on_release = False
            else:
                self._narrow_on_release = True
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        index = self.block_at(event.position())
        if index >= 0:
            self.block_activated.emit(index)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        if self._press_position is None or self._press_index < 0:
            return
        distance = (event.position().toPoint() - self._press_position).manhattanLength()
        if distance < QApplication.startDragDistance():
            return
        dragged = (
            sorted(self.selected_indices)
            if self._press_index in self.selected_indices
            else [self._press_index]
        )
        mime = QMimeData()
        mime.setData(FORM_BLOCK_MIME, QByteArray(json.dumps(dragged).encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        self._press_position = None
        self._narrow_on_release = False
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        if self._narrow_on_release and self._press_index >= 0:
            # A click (not a drag) on a selected block selects just that block.
            self.selection_requested.emit(self._press_index, False, False)  # noqa: FBT003
        self._narrow_on_release = False
        self._press_position = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt override)
        if event.key() in {Qt.Key.Key_Delete, Qt.Key.Key_Backspace}:
            self.delete_requested.emit()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 (Qt override)
        if _accepts(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802 (Qt override)
        if not _accepts(event.mimeData()):
            return
        self.drop_index = self.insert_index_at(event.position())
        self.update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802 (Qt override)
        del event
        self.drop_index = None
        self.update()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 (Qt override)
        self.drop_index = None
        self.update()
        mime = event.mimeData()
        index = self.insert_index_at(event.position())
        if mime.hasFormat(FORM_BLOCK_MIME):
            moving = json.loads(bytes(mime.data(FORM_BLOCK_MIME).data()).decode())
            self.blocks_moved.emit(moving, index)
        elif mime.hasFormat(LIBRARY_BLOCK_MIME):
            data = json.loads(bytes(mime.data(LIBRARY_BLOCK_MIME).data()).decode())
            self.library_block_dropped.emit(data["kind"], data["id"], index)
        else:
            return
        event.acceptProposedAction()


def library_block_mime(kind: str, item_id: str) -> QMimeData:
    """The drag data for a library block, as the palettes offer it."""
    mime = QMimeData()
    mime.setData(
        LIBRARY_BLOCK_MIME,
        QByteArray(json.dumps({"kind": kind, "id": item_id}).encode()),
    )
    return mime


def _accepts(mime: QMimeData) -> bool:
    return mime.hasFormat(FORM_BLOCK_MIME) or mime.hasFormat(LIBRARY_BLOCK_MIME)
