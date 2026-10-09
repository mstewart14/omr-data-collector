from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QStackedWidget,
    QWidget,
)

from omr_data_collector.constants import ANSWER_TYPES
from omr_data_collector.i18n import tr

if TYPE_CHECKING:
    from omr_data_collector.models.AnswerSpec import AnswerSpec

CHOICE_ROWS_VISIBLE = 5


class AnswerEditor(QStackedWidget):
    """Edits one captured answer, with the control its kind of answer needs.

    One choice (or yes/no): a list to pick from, with "Nothing marked" first.
    Any number of choices: a list of check boxes. Written: a line to type in.
    ``current_editor`` is the control showing, which the field's label names.
    """

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.choice_combo = QComboBox()
        self.choices_list = QListWidget()
        self.choices_list.setMaximumHeight(
            self.choices_list.fontMetrics().lineSpacing() * (CHOICE_ROWS_VISIBLE + 1)
        )
        self.text_edit = QLineEdit()
        for editor in (self.choice_combo, self.choices_list, self.text_edit):
            self.addWidget(editor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.currentChanged.connect(self.updateGeometry)
        self.choice_combo.currentIndexChanged.connect(self.changed)
        self.choices_list.itemChanged.connect(self.changed)
        self.text_edit.textEdited.connect(self.changed)
        self._spec: AnswerSpec | None = None

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        # As big as the control showing, not the biggest of them (the list).
        return self.current_editor.sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return self.current_editor.minimumSizeHint()

    @property
    def current_editor(self) -> QWidget:
        return self.currentWidget() or self.choice_combo

    def set_answer(self, spec: AnswerSpec, values: tuple[str, ...]) -> None:
        """Show ``values`` in the control for ``spec``'s kind of answer."""
        self._spec = spec
        blockers = [
            QSignalBlocker(editor)
            for editor in (self.choice_combo, self.choices_list, self.text_edit)
        ]
        if spec.answer_type == ANSWER_TYPES.MANY_CHOICES:
            self.choices_list.clear()
            for choice in spec.choices:
                item = QListWidgetItem(choice.label)
                item.setData(Qt.ItemDataRole.UserRole, choice.output)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if choice.output in values
                    else Qt.CheckState.Unchecked
                )
                self.choices_list.addItem(item)
            self.setCurrentWidget(self.choices_list)
        elif spec.answer_type == ANSWER_TYPES.WRITTEN:
            self.text_edit.setText(values[0] if values else "")
            self.setCurrentWidget(self.text_edit)
        else:
            self.choice_combo.clear()
            self.choice_combo.addItem(tr("Nothing marked"), None)
            for choice in spec.choices:
                self.choice_combo.addItem(choice.label, choice.output)
            if len(values) > 1:
                # Two marked where one is allowed: shown, to be settled.
                self.choice_combo.addItem(tr("More than one marked"), list(values))
            index = (
                self.choice_combo.count() - 1
                if len(values) > 1
                else max(self.choice_combo.findData(values[0]), 0)
                if values
                else 0
            )
            self.choice_combo.setCurrentIndex(index)
            self.setCurrentWidget(self.choice_combo)
        del blockers

    def values(self) -> tuple[str, ...]:
        """The answer's values as now entered."""
        if self._spec is None:
            return ()
        if self.currentWidget() is self.choices_list:
            return tuple(
                item.data(Qt.ItemDataRole.UserRole)
                for item in (
                    self.choices_list.item(row)
                    for row in range(self.choices_list.count())
                )
                if item is not None and item.checkState() == Qt.CheckState.Checked
            )
        if self.currentWidget() is self.text_edit:
            text = self.text_edit.text().strip()
            return (text,) if text else ()
        data = self.choice_combo.currentData()
        if data is None:
            return ()
        return tuple(data) if isinstance(data, (list, tuple)) else (data,)
