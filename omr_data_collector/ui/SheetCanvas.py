"""A captured sheet to check and fill in where it is: click an answer and type.

The page is shown straightened, as read, with every answer's current value drawn
over it: the text typed for handwriting, and a ring round each chosen bubble.
Clicking a handwritten answer opens a box over it to type in at once; clicking a
bubble marks it. Tab and Shift+Tab go through the answers in reading order (from
a typing box, on to the next answer typed in: Enter does too), and the arrow
keys go to the nearest answer that way. On a bubble answer the
number keys choose (1 for the first choice), Space marks or clears a yes/no
bubble and Delete clears the answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImageReader,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QLineEdit, QSizePolicy, QWidget

from omr_data_collector.constants import ANSWER_TYPES
from omr_data_collector.i18n import tr
from omr_data_collector.ui.date_time_typing import fill_separators

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtGui import QMouseEvent, QPaintEvent, QResizeEvent, QWheelEvent

Rect = tuple[int, int, int, int]

CURRENT_COLOR = QColor("#0b57d0")
VALUE_COLOR = QColor("#0b57d0")
PROBLEM_COLOR = QColor("#b3261e")
VALUE_BACKGROUND = QColor(255, 255, 255, 215)
# The box typed into over handwriting: mostly see-through, so the writing it's
# copied from still shows, with just enough white behind the typing to read it.
EDITOR_BACKGROUND = QColor(255, 255, 255, 51)
CURRENT_PEN_PX = 3
RING_PEN_PX = 3
# Room round a close-up so the writing isn't cut off at the edges of its box.
CLOSE_UP_MARGIN_PX = 12
MIN_FONT_POINTS = 9
ZOOM_STEP = 1.25
MIN_ZOOM, MAX_ZOOM = 0.5, 4.0
MIN_VIEW_SIZE = QSize(260, 340)


@dataclass(frozen=True)
class CanvasAnswer:
    """One answer as the sheet shows it: where it is, how it's answered, its value.

    ``choices`` are the printed choices as (saved value, label), in bubble order;
    for yes/no, ``empty_value`` is what an unmarked bubble saves. ``entry`` is
    where a written answer's typing goes, after its label (all of ``rect`` if
    not given); ``entry_cells``, a date or time's format, which typing is laid
    out in (``date_time_typing``), shown as ``entry_hint`` until typed in.
    """

    name: str
    answer_type: str
    rect: Rect
    bubbles: tuple[Rect, ...] = ()
    entry: Rect | None = None
    entry_cells: tuple[str, ...] | None = None
    entry_hint: str = ""
    choices: tuple[tuple[str, str], ...] = ()
    empty_value: str = ""
    values: tuple[str, ...] = ()
    problem: str = ""

    @property
    def written(self) -> bool:
        return self.answer_type == ANSWER_TYPES.WRITTEN


def upright_pixmap(path: Path) -> QPixmap:
    """The image at ``path`` the way up it was taken.

    A phone keeps a photo sideways with a note to turn it (its EXIF
    orientation); Qt only follows that when asked, as OpenCV does when reading.
    """
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    return QPixmap.fromImage(reader.read())


class SheetCanvas(QWidget):
    """The straightened sheet, with its answers to check and fill in on it."""

    # The row (answer index) now current.
    current_changed = Signal(int)
    # An answer's new values, typed or marked on the sheet.
    values_edited = Signal(int, tuple)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(MIN_VIEW_SIZE)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(tr("Sheet"))
        self._pixmap = QPixmap()
        self._answers: list[CanvasAnswer] = []
        self._current: int | None = None
        self._zoom = 1.0
        self._fit_width = MIN_VIEW_SIZE.width()

        self.editor = QLineEdit(self)
        self.editor.hide()
        self.editor.setFrame(True)
        # Fixed colours, like the rest of what's drawn over the page: they sit
        # on the paper, not on the desktop theme. Selected text stays solid.
        back = EDITOR_BACKGROUND
        background = (
            f"rgba({back.red()}, {back.green()}, {back.blue()}, {back.alpha()})"
        )
        text = VALUE_COLOR.name()
        self.editor.setStyleSheet(
            f"QLineEdit {{ background: {background}; color: {text};"
            f" border: {CURRENT_PEN_PX}px solid {text}; font-weight: bold;"
            f" selection-background-color: {text}; selection-color: white; }}"
        )
        self.editor.textEdited.connect(self._on_text_edited)
        self.editor.installEventFilter(self)

    # --- What it shows -----------------------------------------------------------

    def show_image(self, path: Path | None, description: str) -> None:
        self._pixmap = upright_pixmap(path) if path is not None else QPixmap()
        self.setAccessibleDescription(description)
        self._relayout()

    def has_image(self) -> bool:
        return not self._pixmap.isNull()

    def set_answers(self, answers: list[CanvasAnswer]) -> None:
        """Every answer on the page, in reading order; keeps the current one."""
        self._answers = list(answers)
        if self._current is not None and self._current >= len(self._answers):
            self._current = None
        self._place_editor()
        self.update()

    def update_answer(self, row: int, answer: CanvasAnswer) -> None:
        if 0 <= row < len(self._answers):
            self._answers[row] = answer
            text = answer.values[0] if answer.values else ""
            if row == self._current and answer.written and self.editor.text() != text:
                self.editor.setText(text)
            self.update()

    def current(self) -> int | None:
        return self._current

    def answer(self, row: int) -> CanvasAnswer:
        return self._answers[row]

    def set_current(self, row: int | None, *, focus: bool = False) -> None:
        """Make ``row`` the current answer; with ``focus``, ready to type in."""
        if row is not None and not 0 <= row < len(self._answers):
            row = None
        changed = row != self._current
        self._current = row
        self._place_editor()
        if focus:
            self._focus_current()
        self.update()
        if changed and row is not None:
            self.current_changed.emit(row)

    def answer_rect_in_view(self, row: int) -> QRect:
        """Where an answer is drawn, in this widget's pixels (for scrolling to it)."""
        return self._to_view(self._answers[row].rect).toAlignedRect()

    def close_up(self, rect: Rect) -> QPixmap:
        """The part of the page in ``rect``, with a little margin round it."""
        if self._pixmap.isNull():
            return QPixmap()
        area = QRect(*rect).adjusted(
            -CLOSE_UP_MARGIN_PX,
            -CLOSE_UP_MARGIN_PX,
            CLOSE_UP_MARGIN_PX,
            CLOSE_UP_MARGIN_PX,
        )
        return self._pixmap.copy(area.intersected(self._pixmap.rect()))

    # --- Size and zoom ------------------------------------------------------------

    def set_fit_width(self, width: int) -> None:
        """The width to fit the page to at zoom 1 (the space it's shown in)."""
        self._fit_width = max(width, MIN_VIEW_SIZE.width())
        self._relayout()

    def zoom_by(self, factor: float) -> None:
        self._zoom = min(max(self._zoom * factor, MIN_ZOOM), MAX_ZOOM)
        self._relayout()

    def _scale(self) -> float:
        if self._pixmap.isNull():
            return 1.0
        return self._fit_width * self._zoom / self._pixmap.width()

    def _relayout(self) -> None:
        if self._pixmap.isNull():
            self.setFixedSize(QSize(self._fit_width, MIN_VIEW_SIZE.height()))
        else:
            scale = self._scale()
            self.setFixedSize(
                QSize(
                    round(self._pixmap.width() * scale),
                    round(self._pixmap.height() * scale),
                )
            )
        self._place_editor()
        self.update()

    def _to_view(self, rect: Rect) -> QRectF:
        scale = self._scale()
        x, y, width, height = rect
        return QRectF(x * scale, y * scale, width * scale, height * scale)

    # --- Painting -------------------------------------------------------------------

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
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(
            QRectF(self.rect()), self._pixmap, QRectF(self._pixmap.rect())
        )
        for row, answer in enumerate(self._answers):
            self._paint_answer(painter, answer, current=row == self._current)

    def _paint_answer(
        self, painter: QPainter, answer: CanvasAnswer, *, current: bool
    ) -> None:
        area = self._to_view(answer.rect)
        if answer.problem:
            painter.setPen(QPen(PROBLEM_COLOR, CURRENT_PEN_PX, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(area.adjusted(1, 1, -1, -1))
        if current:
            painter.setPen(QPen(CURRENT_COLOR, CURRENT_PEN_PX))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(area)
        if answer.written:
            if answer.values and not (current and self.editor.isVisible()):
                entry = self._to_view(answer.entry or answer.rect)
                self._paint_value(painter, entry, answer.values[0])
            return
        painter.setPen(QPen(VALUE_COLOR, RING_PEN_PX))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for (value, _label), bubble in zip(
            answer.choices, answer.bubbles, strict=False
        ):
            if value in answer.values:
                ring = self._to_view(bubble)
                grow = ring.width() * 0.35
                painter.drawEllipse(ring.adjusted(-grow, -grow, grow, grow))

    def _paint_value(self, painter: QPainter, area: QRectF, text: str) -> None:
        """Typed text over its handwriting, legible but not hiding all of it."""
        font = QFont(self.font())
        font.setPixelSize(max(round(area.height() * 0.45), MIN_FONT_POINTS))
        font.setBold(True)
        painter.setFont(font)
        width = min(painter.fontMetrics().horizontalAdvance(text) + 8, area.width())
        height = painter.fontMetrics().height() + 2
        box = QRectF(area.left() + 2, area.bottom() - height - 2, width, height)
        painter.fillRect(box, VALUE_BACKGROUND)
        painter.setPen(VALUE_COLOR)
        painter.drawText(
            box.adjusted(4, 0, -4, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

    # --- Typing over a handwritten answer -------------------------------------------

    def _place_editor(self) -> None:
        answer = self._current_answer()
        if answer is None or not answer.written or self._pixmap.isNull():
            if self.editor.hasFocus():
                # Else hiding it moves focus on by itself, a second step.
                self.setFocus(Qt.FocusReason.OtherFocusReason)
            self.editor.hide()
            return
        # Where the answer is written, so the typing covers the handwriting.
        area = self._to_view(answer.entry or answer.rect).toAlignedRect()
        font = QFont(self.font())
        font.setPixelSize(max(round(area.height() * 0.45), MIN_FONT_POINTS))
        self.editor.setFont(font)
        height = max(self.editor.sizeHint().height(), round(area.height() * 0.6))
        self.editor.setGeometry(
            area.left(), area.bottom() - height, max(area.width(), 80), height
        )
        text = answer.values[0] if answer.values else ""
        if self.editor.text() != text:
            self.editor.setText(text)
        self.editor.setPlaceholderText(answer.entry_hint)
        self.editor.setAccessibleName(answer.name)
        self.editor.setAccessibleDescription(answer.problem)
        self.editor.show()

    def _focus_current(self) -> None:
        if self.editor.isVisible():
            self.editor.setFocus(Qt.FocusReason.OtherFocusReason)
            self.editor.selectAll()
        else:
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_text_edited(self, _text: str) -> None:
        answer = self._current_answer()
        if answer is None or self._current is None:
            return
        fill_separators(self.editor, answer.entry_cells)
        cleaned = self.editor.text().strip()
        self.values_edited.emit(self._current, (cleaned,) if cleaned else ())

    # --- Mouse ----------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        position = event.position()
        for row, answer in enumerate(self._answers):
            for index, bubble in enumerate(answer.bubbles):
                ring = self._to_view(bubble)
                grow = ring.width() * 0.5
                if ring.adjusted(-grow, -grow, grow, grow).contains(position):
                    self.set_current(row, focus=True)
                    self._mark(index)
                    return
        row = self._answer_at(position)
        if row is not None:
            self.set_current(row, focus=True)
        else:
            super().mousePressEvent(event)

    def _answer_at(self, position: QPointF) -> int | None:
        """The answer under ``position``: the smallest region holding it."""
        found = [
            (answer.rect[2] * answer.rect[3], row)
            for row, answer in enumerate(self._answers)
            if self._to_view(answer.rect).contains(position)
        ]
        return min(found)[1] if found else None

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 (Qt override)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(ZOOM_STEP if event.angleDelta().y() > 0 else 1 / ZOOM_STEP)
            event.accept()
        else:
            super().wheelEvent(event)

    # --- Keyboard -------------------------------------------------------------------

    def focusNextPrevChild(self, next_child: bool) -> bool:  # noqa: FBT001, N802 (Qt override)
        # Tab goes through the answers on the sheet; past the last (or before
        # the first) it goes on to the next control, so it never traps focus.
        if self._move_in_order(1 if next_child else -1):
            return True
        return super().focusNextPrevChild(next_child)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt override)
        if self._handle_navigation(event) or self._handle_choice_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt override)
        if (
            watched is self.editor
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and self._editor_key(event)
        ):
            return True
        return super().eventFilter(watched, event)

    def _editor_key(self, event: QKeyEvent) -> bool:
        """Keys in the typing box: move on, or let it edit the text."""
        key = event.key()
        # Tab is taken here, before Qt passes it up the widget tree: it goes to
        # the next answer typed in (the bubbles between are read already), or
        # past the last one on to the next control.
        if key in {Qt.Key.Key_Tab, Qt.Key.Key_Backtab}:
            shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            step = -1 if key == Qt.Key.Key_Backtab or shift else 1
            if not self._move_in_order(step, written=True):
                QWidget.focusNextPrevChild(self, step > 0)
            return True
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            return self._move_in_order(1, written=True) or True
        if key in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
            return self._handle_navigation(event)
        at_start = (
            self.editor.cursorPosition() == 0 and not self.editor.hasSelectedText()
        )
        at_end = self.editor.cursorPosition() == len(self.editor.text())
        if (key == Qt.Key.Key_Left and at_start) or (
            key == Qt.Key.Key_Right and at_end
        ):
            return self._handle_navigation(event)
        return False

    def _handle_navigation(self, event: QKeyEvent) -> bool:
        directions = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if event.key() in directions:
            target = self._nearest(*directions[Qt.Key(event.key())])
            if target is not None:
                self.set_current(target, focus=True)
            return True
        control = event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if event.matches(QKeySequence.StandardKey.ZoomIn) or (
            control and event.key() == Qt.Key.Key_Equal
        ):
            self.zoom_by(ZOOM_STEP)
            return True
        if event.matches(QKeySequence.StandardKey.ZoomOut):
            self.zoom_by(1 / ZOOM_STEP)
            return True
        return False

    def _handle_choice_key(self, event: QKeyEvent) -> bool:
        """Number keys choose, Space marks yes/no, Delete clears."""
        answer = self._current_answer()
        if answer is None or answer.written:
            return False
        key = event.key()
        if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            index = key - Qt.Key.Key_1
            if index < len(answer.choices):
                self._mark(index)
            return True
        if key == Qt.Key.Key_Space and answer.answer_type == ANSWER_TYPES.YES_NO:
            self._mark(0)
            return True
        if key in {Qt.Key.Key_Delete, Qt.Key.Key_Backspace, Qt.Key.Key_0}:
            empty = (answer.empty_value,) if answer.empty_value else ()
            self.values_edited.emit(self._current, empty)
            return True
        return False

    def _mark(self, index: int) -> None:
        """Mark the current answer's ``index``th bubble, as a pen would."""
        answer = self._current_answer()
        if answer is None or self._current is None or index >= len(answer.choices):
            return
        value = answer.choices[index][0]
        if answer.answer_type == ANSWER_TYPES.MANY_CHOICES:
            values = (
                tuple(v for v in answer.values if v != value)
                if value in answer.values
                else tuple(
                    v for v, _ in answer.choices if v in answer.values or v == value
                )
            )
        elif answer.answer_type == ANSWER_TYPES.YES_NO:
            values = (answer.empty_value,) if value in answer.values else (value,)
        else:
            values = () if answer.values == (value,) else (value,)
        self.values_edited.emit(self._current, values)

    def _move_in_order(self, step: int, *, written: bool = False) -> bool:
        """Go to the next answer (``step`` 1) or the one before (-1).

        Only to answers typed in if ``written``. False if there is none.
        """
        if self._current is None:
            start = -1 if step > 0 else len(self._answers)
        else:
            start = self._current
        target = start + step
        while 0 <= target < len(self._answers):
            if not written or self._answers[target].written:
                self.set_current(target, focus=True)
                return True
            target += step
        return False

    def _nearest(self, dx: int, dy: int) -> int | None:
        """The closest answer from the current one in a direction, if any."""
        answer = self._current_answer()
        if answer is None:
            return 0 if self._answers else None
        x, y, width, height = answer.rect
        cx, cy = x + width / 2, y + height / 2
        best: tuple[float, int] | None = None
        for row, other in enumerate(self._answers):
            if row == self._current:
                continue
            ox, oy, ow, oh = other.rect
            ocx, ocy = ox + ow / 2, oy + oh / 2
            along = (ocx - cx) * dx + (ocy - cy) * dy
            if along <= 0:
                continue
            across = abs((ocx - cx) * dy) + abs((ocy - cy) * dx)
            # Straight ahead counts for more than off to the side.
            score = along + 3 * across
            if best is None or score < best[0]:
                best = (score, row)
        return best[1] if best else None

    def _current_answer(self) -> CanvasAnswer | None:
        if self._current is None or not 0 <= self._current < len(self._answers):
            return None
        return self._answers[self._current]

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._place_editor()
