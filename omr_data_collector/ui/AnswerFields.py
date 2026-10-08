from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from omr_data_collector.constants import (
    ANSWER_TYPES,
    CHECK_DIGIT_SCHEMES,
    DATE_TIME_FORMATS,
    MAX_CHOICES,
    MAX_WRITTEN_CHARACTERS,
    WRITTEN_DATA_TYPES,
)
from omr_data_collector.i18n import tr
from omr_data_collector.models.AnswerSpec import (
    CHOICE_ANSWER_TYPES,
    AnswerSpec,
    Choice,
)
from omr_data_collector.ui.form_helpers import add_field_row

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QFormLayout, QLabel


def answer_type_labels() -> dict[str, str]:
    return {
        ANSWER_TYPES.YES_NO: tr("Yes/no (one bubble, marked or empty)"),
        ANSWER_TYPES.ONE_CHOICE: tr("One choice from a list"),
        ANSWER_TYPES.MANY_CHOICES: tr("Any number of choices from a list"),
        ANSWER_TYPES.WRITTEN: tr("Written answer"),
    }


def data_type_labels() -> dict[str, str]:
    return {
        WRITTEN_DATA_TYPES.FREE_TEXT: tr("Free text"),
        WRITTEN_DATA_TYPES.NUMBER: tr("Number"),
        WRITTEN_DATA_TYPES.DATE_TIME: tr("Date/time"),
        WRITTEN_DATA_TYPES.ID: tr("ID"),
    }


def check_digit_labels() -> dict[str, str]:
    return {
        CHECK_DIGIT_SCHEMES.NONE: tr("None", "no check digit"),
        # Named after their inventors.
        CHECK_DIGIT_SCHEMES.DAMM: "Damm",
        CHECK_DIGIT_SCHEMES.VERHOEFF: "Verhoeff",
    }


def date_time_format_labels() -> dict[str, str]:
    """How each date/time format is shown, in the language's letters.

    Y, M, D, H and M stand for year, month, day, hour and minute.
    """
    return {
        "YYYY/MM/DD": tr("YYYY/MM/DD"),
        "HH:MM": tr("HH:MM"),
        "YYYY/MM/DD HH:MM": tr("YYYY/MM/DD HH:MM"),
    }


def list_table_description() -> str:
    return tr(
        "Each row is one bubble: the words printed beside it, and what is saved "
        "when it is marked (blank saves the printed words)."
    )


def yes_no_row_labels() -> list[str]:
    return [tr("Marked"), tr("Left empty")]


def yes_no_table_description() -> str:
    return tr(
        "A yes/no answer is one bubble. The Marked row's words are printed beside "
        "it and saved when it is marked; the Left empty row's are saved when it "
        "isn't (and never printed). Blank Saved as saves the words."
    )


LABEL_COLUMN, OUTPUT_COLUMN = 0, 1
# Number limits are optional; the spin box's lowest value stands for "no limit".
NO_LIMIT = -(2**31) + 1
CHOICE_ROWS_VISIBLE = 5


class AnswerFields:
    """The rows that define how an answer is collected, added to a page's form.

    Not a widget of its own: its labels and controls go straight into the given
    form, as siblings, which is how screen readers learn each control's label.
    Rows that don't apply to the chosen answer type are hidden.
    """

    def __init__(
        self,
        form: QFormLayout,
        field_widgets: dict[str, QWidget],
        field_labels: dict[str, QLabel],
        error_labels: dict[str, QLabel],
        on_change: Callable[[], None],
    ) -> None:
        self._form = form
        self._on_change = on_change
        # Each kind of choice list keeps its own entries, so switching between a
        # yes/no answer and a list (and back) loses nothing.
        self._yes_no_choices = AnswerSpec.default(ANSWER_TYPES.YES_NO).choices
        self._list_choices = AnswerSpec.default(ANSWER_TYPES.ONE_CHOICE).choices
        self._showing_type = ANSWER_TYPES.YES_NO

        self.answer_type_combo = _combo(answer_type_labels())
        self.choices_table = QTableWidget(0, 2)
        self.choices_table.setHorizontalHeaderLabels([tr("Printed"), tr("Saved as")])
        header = self.choices_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setToolTip(
            tr(
                '"Saved as" is the value in exported data; leave it blank to save the '
                "printed words."
            )
        )
        self.choices_table.setAccessibleDescription(list_table_description())
        self.choices_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.choices_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        # Tab moves on to the next control rather than from cell to cell, so the
        # table never traps keyboard users; arrow keys move between cells.
        self.choices_table.setTabKeyNavigation(False)
        row_height = self.choices_table.verticalHeader().defaultSectionSize()
        self.choices_table.setMinimumHeight(
            row_height * (CHOICE_ROWS_VISIBLE + 1) + 2 * self.choices_table.frameWidth()
        )

        self.add_choice_button = QPushButton(tr("Add &choice"))
        self.remove_choice_button = QPushButton(tr("Remo&ve choice"))
        self.move_up_button = QPushButton(tr("Move up"))
        self.move_down_button = QPushButton(tr("Move down"))
        self.choice_buttons = QWidget()
        self.choice_buttons.setAccessibleName(tr("Choice actions"))
        buttons_layout = QHBoxLayout(self.choice_buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        for button in (
            self.add_choice_button,
            self.remove_choice_button,
            self.move_up_button,
            self.move_down_button,
        ):
            buttons_layout.addWidget(button)
        buttons_layout.addStretch()

        self.characters_spin = QSpinBox()
        self.characters_spin.setRange(1, MAX_WRITTEN_CHARACTERS)
        self.characters_spin.setToolTip(tr("How many boxes are printed for the answer"))
        self.data_type_combo = _combo(data_type_labels())
        self.minimum_spin = _limit_spin(tr("No minimum"))
        self.maximum_spin = _limit_spin(tr("No maximum"))
        self.date_format_combo = QComboBox()
        for date_format in DATE_TIME_FORMATS:
            self.date_format_combo.addItem(
                date_time_format_labels()[date_format], date_format
            )
        self.check_digit_combo = _combo(check_digit_labels())
        self.check_digit_combo.setToolTip(
            tr("The last digit of each ID is checked, catching most mistyped IDs")
        )

        for key, label_text, widget in (
            ("answer_type", tr("&Kind of answer"), self.answer_type_combo),
            ("choices", tr("C&hoices"), self.choices_table),
        ):
            field_labels[key], error_labels[key] = add_field_row(
                form, label_text, widget
            )
            field_widgets[key] = widget
        form.addRow("", self.choice_buttons)
        for key, label_text, widget in (
            ("data_type", tr("Data t&ype"), self.data_type_combo),
            ("max_characters", tr("Si&ze (characters)"), self.characters_spin),
            ("number_minimum", tr("M&inimum"), self.minimum_spin),
            ("number_maximum", tr("Ma&ximum"), self.maximum_spin),
            ("date_time_format", tr("Date &written as"), self.date_format_combo),
            ("check_digit", tr("Check di&git"), self.check_digit_combo),
        ):
            field_labels[key], error_labels[key] = add_field_row(
                form, label_text, widget
            )
            field_widgets[key] = widget

        self._connect_signals()
        self.set_spec(AnswerSpec.default(ANSWER_TYPES.YES_NO))

    def focus_chain(self) -> list[QWidget]:
        """The controls in tab order."""
        return [
            self.answer_type_combo,
            self.choices_table,
            self.add_choice_button,
            self.remove_choice_button,
            self.move_up_button,
            self.move_down_button,
            self.data_type_combo,
            self.characters_spin,
            self.minimum_spin,
            self.maximum_spin,
            self.date_format_combo,
            self.check_digit_combo,
        ]

    def spec(self) -> AnswerSpec:
        """The answer as currently entered, normalized."""
        answer_type = self.answer_type_combo.currentData()
        self._stash_choices()
        choices: tuple[Choice, ...] = ()
        if answer_type == ANSWER_TYPES.YES_NO:
            choices = self._yes_no_choices
        elif answer_type in CHOICE_ANSWER_TYPES:
            choices = self._list_choices
        return AnswerSpec(
            answer_type=answer_type,
            choices=choices,
            max_characters=self.characters_spin.value(),
            data_type=self.data_type_combo.currentData(),
            number_minimum=_limit_value(self.minimum_spin),
            number_maximum=_limit_value(self.maximum_spin),
            date_time_format=self.date_format_combo.currentData(),
            check_digit=self.check_digit_combo.currentData(),
        ).normalized()

    def set_spec(self, spec: AnswerSpec) -> None:
        if spec.answer_type == ANSWER_TYPES.YES_NO:
            self._yes_no_choices = spec.choices
            self._list_choices = AnswerSpec.default(ANSWER_TYPES.ONE_CHOICE).choices
        elif spec.answer_type in CHOICE_ANSWER_TYPES:
            self._list_choices = spec.choices
            self._yes_no_choices = AnswerSpec.default(ANSWER_TYPES.YES_NO).choices
        else:
            self._yes_no_choices = AnswerSpec.default(ANSWER_TYPES.YES_NO).choices
            self._list_choices = AnswerSpec.default(ANSWER_TYPES.ONE_CHOICE).choices
        controls = (
            self.answer_type_combo,
            self.data_type_combo,
            self.characters_spin,
            self.minimum_spin,
            self.maximum_spin,
            self.date_format_combo,
            self.check_digit_combo,
            self.choices_table,
        )
        blockers = [QSignalBlocker(control) for control in controls]
        _set_combo(self.answer_type_combo, spec.answer_type)
        _set_combo(self.data_type_combo, spec.data_type)
        self.characters_spin.setValue(spec.max_characters)
        _set_limit(self.minimum_spin, spec.number_minimum)
        _set_limit(self.maximum_spin, spec.number_maximum)
        _set_combo(self.date_format_combo, spec.date_time_format)
        _set_combo(self.check_digit_combo, spec.check_digit)
        self._showing_type = spec.answer_type
        self._fill_choices_table()
        del blockers
        self._update_rows()

    # --- Choices ------------------------------------------------------------------

    def add_choice(self) -> None:
        row = self.choices_table.rowCount()
        self.choices_table.insertRow(row)
        self.choices_table.setItem(row, LABEL_COLUMN, QTableWidgetItem(""))
        self.choices_table.setItem(row, OUTPUT_COLUMN, QTableWidgetItem(""))
        self.choices_table.setCurrentCell(row, LABEL_COLUMN)
        self.choices_table.setFocus(Qt.FocusReason.OtherFocusReason)
        new_label = self.choices_table.item(row, LABEL_COLUMN)
        if new_label is not None:
            self.choices_table.editItem(new_label)
        self._choices_changed()

    def remove_choice(self) -> None:
        row = self.choices_table.currentRow()
        if row < 0:
            return
        self.choices_table.removeRow(row)
        if self.choices_table.rowCount():
            self.choices_table.setCurrentCell(
                min(row, self.choices_table.rowCount() - 1), LABEL_COLUMN
            )
        self._choices_changed()

    def move_choice(self, offset: int) -> None:
        row = self.choices_table.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < self.choices_table.rowCount():
            return
        self._stash_choices()
        choices = list(self._current_choices())
        choices[row], choices[target] = choices[target], choices[row]
        self._store_choices(tuple(choices))
        self._fill_choices_table()
        self.choices_table.setCurrentCell(target, self.choices_table.currentColumn())
        self._choices_changed()

    # --- Internals ----------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.answer_type_combo.currentIndexChanged.connect(self._answer_type_changed)
        self.data_type_combo.currentIndexChanged.connect(self._changed)
        self.date_format_combo.currentIndexChanged.connect(self._changed)
        for spin in (self.characters_spin, self.minimum_spin, self.maximum_spin):
            spin.valueChanged.connect(self._changed)
        self.check_digit_combo.currentIndexChanged.connect(self._changed)
        self.choices_table.itemChanged.connect(self._changed)
        self.choices_table.currentCellChanged.connect(self._update_choice_buttons)
        self.add_choice_button.clicked.connect(self.add_choice)
        self.remove_choice_button.clicked.connect(self.remove_choice)
        self.move_up_button.clicked.connect(lambda: self.move_choice(-1))
        self.move_down_button.clicked.connect(lambda: self.move_choice(1))

    def _answer_type_changed(self) -> None:
        self._stash_choices()
        self._showing_type = self.answer_type_combo.currentData()
        with QSignalBlocker(self.choices_table):
            self._fill_choices_table()
        self._changed()

    def _changed(self) -> None:
        self._update_rows()
        self._on_change()

    def _choices_changed(self) -> None:
        self._stash_choices()
        self._changed()

    def _current_choices(self) -> tuple[Choice, ...]:
        if self._showing_type == ANSWER_TYPES.YES_NO:
            return self._yes_no_choices
        return self._list_choices

    def _store_choices(self, choices: tuple[Choice, ...]) -> None:
        if self._showing_type == ANSWER_TYPES.YES_NO:
            self._yes_no_choices = choices
        elif self._showing_type in CHOICE_ANSWER_TYPES:
            self._list_choices = choices

    def _stash_choices(self) -> None:
        """Copy the table into the choices of the type it is showing."""
        if self._showing_type not in CHOICE_ANSWER_TYPES:
            return
        self._store_choices(
            tuple(
                Choice(
                    label=_cell_text(self.choices_table, row, LABEL_COLUMN),
                    output=_cell_text(self.choices_table, row, OUTPUT_COLUMN),
                )
                for row in range(self.choices_table.rowCount())
            )
        )

    def _fill_choices_table(self) -> None:
        choices = (
            self._current_choices() if self._showing_type in CHOICE_ANSWER_TYPES else ()
        )
        self.choices_table.setRowCount(0)
        yes_no = self._showing_type == ANSWER_TYPES.YES_NO
        self.choices_table.verticalHeader().setVisible(yes_no)
        if yes_no:
            self.choices_table.setAccessibleDescription(yes_no_table_description())
        else:
            self.choices_table.setAccessibleDescription(list_table_description())
        for row, choice in enumerate(choices):
            self.choices_table.insertRow(row)
            self.choices_table.setItem(
                row, LABEL_COLUMN, QTableWidgetItem(choice.label)
            )
            # Shown blank when it just repeats the printed words, as it was entered.
            output = "" if choice.output == choice.label else choice.output
            self.choices_table.setItem(row, OUTPUT_COLUMN, QTableWidgetItem(output))
        if yes_no:
            self.choices_table.setVerticalHeaderLabels(yes_no_row_labels())

    def _update_rows(self) -> None:
        answer_type = self.answer_type_combo.currentData()
        data_type = self.data_type_combo.currentData()
        choice_type = answer_type in CHOICE_ANSWER_TYPES
        written = answer_type == ANSWER_TYPES.WRITTEN
        visible = {
            self.choices_table: choice_type,
            self.choice_buttons: choice_type,
            self.data_type_combo: written,
            self.characters_spin: written,
            self.minimum_spin: written and data_type == WRITTEN_DATA_TYPES.NUMBER,
            self.maximum_spin: written and data_type == WRITTEN_DATA_TYPES.NUMBER,
            self.date_format_combo: written
            and data_type == WRITTEN_DATA_TYPES.DATE_TIME,
            self.check_digit_combo: written and data_type == WRITTEN_DATA_TYPES.ID,
        }
        for widget, show in visible.items():
            self._form.setRowVisible(widget, show)

        # A date/time's format fixes its length: one box per character.
        is_date = data_type == WRITTEN_DATA_TYPES.DATE_TIME
        self.characters_spin.setEnabled(not is_date)
        if is_date:
            with QSignalBlocker(self.characters_spin):
                self.characters_spin.setValue(len(self.date_format_combo.currentData()))
        self._update_choice_buttons()

    def _update_choice_buttons(self) -> None:
        yes_no = self.answer_type_combo.currentData() == ANSWER_TYPES.YES_NO
        rows = self.choices_table.rowCount()
        row = self.choices_table.currentRow()
        # A yes/no answer always has exactly two rows, marked and left empty: they
        # can be reworded and swapped, not added or removed.
        self.add_choice_button.setEnabled(not yes_no and rows < MAX_CHOICES)
        self.remove_choice_button.setEnabled(not yes_no and row >= 0)
        self.move_up_button.setEnabled(row > 0)
        self.move_down_button.setEnabled(0 <= row < rows - 1)


def _combo(labels: dict[str, str]) -> QComboBox:
    combo = QComboBox()
    for value, label in labels.items():
        combo.addItem(label, value)
    return combo


def _set_combo(combo: QComboBox, value: str) -> None:
    combo.setCurrentIndex(max(combo.findData(value), 0))


def _limit_spin(no_limit_text: str) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(NO_LIMIT, 2**31 - 1)
    # Shown, and read by screen readers, instead of the sentinel number.
    spin.setSpecialValueText(no_limit_text)
    spin.setValue(NO_LIMIT)
    return spin


def _limit_value(spin: QSpinBox) -> int | None:
    return None if spin.value() == NO_LIMIT else spin.value()


def _set_limit(spin: QSpinBox, value: int | None) -> None:
    spin.setValue(NO_LIMIT if value is None else value)


def _cell_text(table: QTableWidget, row: int, column: int) -> str:
    item = table.item(row, column)
    return item.text() if item is not None else ""
