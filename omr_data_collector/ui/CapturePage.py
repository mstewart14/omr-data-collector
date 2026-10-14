"""Turning photos and scans of filled-in sheets into data (wiki 60001-60004)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QLocale, QObject, QStandardPaths, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from omr_data_collector.constants import ANSWER_TYPES, CAPTURE_STATUSES, PAPER_SIZES
from omr_data_collector.engine.reading import read_capture
from omr_data_collector.export.data_export import (
    collect,
    csv_paths,
    output_files,
    safe_file_name,
    saved_sheet_counts,
    write_csv,
    write_json,
)
from omr_data_collector.i18n import tr
from omr_data_collector.layout.form_layout import layout_form
from omr_data_collector.layout.omr_template import (
    AnswerRegion,
    PageTemplate,
    page_template,
    with_writing_areas,
)
from omr_data_collector.models.Question import Question
from omr_data_collector.models.SheetDetails import SheetDetails
from omr_data_collector.models.TableBlock import TableBlock
from omr_data_collector.storage.capture_store import (
    DuplicateCaptureError,
    add_capture,
    delete_capture,
    image_path,
    likely_duplicates,
    list_captures,
    page_image_path,
    save_capture,
)
from omr_data_collector.storage.export_store import (
    load_export_names,
    save_export_names,
)
from omr_data_collector.storage.form_store import (
    list_forms,
    load_form_version,
    load_printed_layout,
)
from omr_data_collector.storage.organization_store import load_organization
from omr_data_collector.ui.accessibility import (
    announce,
    band_color,
    set_field_error,
    style_error_label,
)
from omr_data_collector.ui.AnswerEditor import AnswerEditor
from omr_data_collector.ui.date_time_typing import typing_cells, typing_hint
from omr_data_collector.ui.ExportDialog import CSV_FORMAT, ExportDialog
from omr_data_collector.ui.ExportNamesDialog import ExportNamesDialog
from omr_data_collector.ui.form_helpers import (
    add_field_row,
    add_shortcut,
    ask_save_discard_cancel,
    confirm_destructive,
)
from omr_data_collector.ui.SheetCanvas import CanvasAnswer, SheetCanvas

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from omr_data_collector.export.data_export import (
        ExportNames,
        FormData,
        OutputFile,
    )
    from omr_data_collector.models.AnswerSpec import AnswerSpec
    from omr_data_collector.models.Capture import Capture, CapturedAnswer
    from omr_data_collector.models.Form import Form

IMAGE_PATTERNS = "*.jpg *.jpeg *.png *.tif *.tiff *.bmp"
NAME_COLUMN, VALUE_COLUMN, NOTE_COLUMN = 0, 1, 2
CLOSE_UP_HEIGHT = 140


def status_text(capture: Capture) -> str:
    """Where a sheet is, in words, for the list of sheets."""
    if capture.status == CAPTURE_STATUSES.WAITING:
        return tr("{file}: waiting to be read").format(file=capture.original_name)
    if capture.status == CAPTURE_STATUSES.UNREADABLE:
        return tr("{file}: couldn't be read").format(file=capture.original_name)
    if capture.status == CAPTURE_STATUSES.READ:
        return tr("{file}: read, to check").format(file=capture.original_name)
    if capture.status == CAPTURE_STATUSES.SAVED:
        return tr("{file}: saved").format(file=capture.original_name)
    return tr("{file}: rejected").format(file=capture.original_name)


def duplicate_warning(alike: list[Capture]) -> str:
    """Say which sheets ``alike`` look like the same filled-in sheet, if any."""
    if not alike:
        return ""
    files = QLocale().createSeparatedList(
        [f'"{capture.original_name}"' for capture in alike]
    )
    return tr(
        "This may be the same sheet as %n other picture(s), {files}: every "
        "bubble is marked the same. If it is, reject all but one.",
        None,
        len(alike),
    ).format(files=files)


def choose_export(
    parent: QWidget,
    forms: list[tuple[Form, int]],
    sheets: dict[str, list[tuple[str, str]]],
    edit_names: Callable[[str], object],
    layout_warning: Callable[[str, list[str] | None], str] | None = None,
) -> tuple[str, str, list[str] | None, bool] | None:
    """Ask which form's data to export, which sheets and as what; None if cancelled."""
    dialog = ExportDialog(parent, forms, sheets, edit_names, layout_warning)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.chosen()


def _details_summary(form: Form | None, capture: Capture) -> str:
    """The sheet details written on a sheet, like "Date 2026/10/08, Shift night"."""
    if form is None:
        return ""
    parts = []
    for answer in capture.answers:
        if not 0 <= answer.block_index < len(form.blocks):
            continue
        content = form.blocks[answer.block_index].content
        if (
            isinstance(content, SheetDetails)
            and answer.column is not None
            and answer.values
        ):
            parts.append(
                tr("{field} {value}").format(
                    field=content.fields[answer.column].name,
                    value=", ".join(answer.values),
                )
            )
    return QLocale().createSeparatedList(parts) if parts else ""


def choose_export_names(
    parent: QWidget, files: list[OutputFile], names: ExportNames
) -> ExportNames | None:
    """Ask for the names of a form's outputs; None if cancelled."""
    dialog = ExportNamesDialog(parent, files, names)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.names()


def mixed_layout_warning(data: FormData) -> str:
    """A warning if the sheets in ``data`` don't all share one layout, else ""."""
    if not data.missing:
        return ""
    columns = [
        tr('"{column}" (not on version {versions})').format(
            column=missing.column,
            versions=QLocale().createSeparatedList([str(v) for v in missing.versions]),
        )
        if missing.table is None
        else tr('"{column}" of the table "{table}" (not on version {versions})').format(
            column=missing.column,
            table=missing.table,
            versions=QLocale().createSeparatedList([str(v) for v in missing.versions]),
        )
        for missing in data.missing
    ]
    return tr(
        "Warning: these sheets were printed from versions of the form with "
        "different columns, so they don't all line up. Columns a sheet's version "
        "didn't have are left blank for it: {columns}."
    ).format(columns=QLocale().createSeparatedList(columns))


def default_file_name(form: Form, now: datetime | None = None) -> str:
    """What an export of ``form`` is called unless named otherwise, no extension.

    It starts with the local date and time (``now``), so exports sort in order.
    """
    now = now or datetime.now().astimezone()
    return safe_file_name(
        tr("{time} {name} v{version}", "Export file name").format(
            time=now.strftime("%Y-%m-%d %H%M"), name=form.name, version=form.version
        )
    )


def choose_export_path(
    parent: QWidget, file_format: str, default_path: Path
) -> Path | None:
    """Ask what to call the exported file and where; None if cancelled.

    For CSV it's the sheets file: each table's file goes beside it.
    """
    if file_format == CSV_FORMAT:
        title, filter_, suffix = (
            tr("Export data as CSV"),
            tr("CSV file (*.csv)"),
            ".csv",
        )
    else:
        title, filter_, suffix = (
            tr("Export data as JSON"),
            tr("JSON file (*.json)"),
            ".json",
        )
    name, _ = QFileDialog.getSaveFileName(
        parent, title, str(default_path.with_suffix(suffix)), filter_
    )
    if not name:
        return None
    path = Path(name)
    return (
        path if path.suffix.casefold() == suffix else path.with_name(path.name + suffix)
    )


def confirm_replacing(parent: QWidget, paths: list[Path]) -> bool:
    """Ask before writing over table files beside the chosen one; True to go on."""
    if not paths:
        return True
    return confirm_destructive(
        parent,
        tr("Replace files?"),
        tr("The tables' files beside it are there already: {files}.").format(
            files=QLocale().createSeparatedList([path.name for path in paths])
        ),
        tr("&Replace them"),
    )


def choose_images(parent: QWidget) -> list[Path]:
    """Ask which photos or scans to add; none if cancelled."""
    names, _ = QFileDialog.getOpenFileNames(
        parent,
        tr("Add images of filled-in sheets"),
        "",
        tr("Images ({patterns})").format(patterns=IMAGE_PATTERNS),
    )
    return [Path(name) for name in names]


class CapturePage(QWidget):
    """Add photos or scans of filled-in sheets, read them, then check the data.

    Each sheet is checked against its own image: the straightened page with the
    answer being checked outlined, a close-up of it, and every answer on the
    page in a list, bubbles as read and handwriting to type in.
    """

    status_message = Signal(str)

    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__()
        self._connection = connection
        self._captures: list[Capture] = []
        self._current: Capture | None = None
        self._form: Form | None = None
        self._template: PageTemplate | None = None
        # The answers as being checked; saved with Save data.
        self._answers: list[CapturedAnswer] = []
        # The row of the answer the editor is showing.
        self._editing_row: int | None = None
        # Where exports are saved: the documents folder, then the last used.
        self._export_folder = Path(
            QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.DocumentsLocation
            )
        )

        # Set while the canvas and the answers list follow each other.
        self._syncing = False
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_sheets_box())
        splitter.addWidget(self._build_sheet_view())
        splitter.addWidget(self._build_check_box())
        # The sheet gets most of the room: it's where answers are typed in.
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        self.shortcuts = [add_shortcut(self, "Ctrl+S", self.save_data)]
        self.initial_focus: QWidget = self.sheet_list
        QWidget.setTabOrder(self.sheet_list, self.add_button)
        for before, after in (
            (self.add_button, self.read_button),
            (self.read_button, self.remove_button),
            (self.remove_button, self.export_button),
            (self.export_button, self.sheet_canvas),
            (self.sheet_canvas, self.answers_table),
            (self.answers_table, self.answer_editor.choice_combo),
            (self.answer_editor.choice_combo, self.answer_editor.choices_list),
            (self.answer_editor.choices_list, self.answer_editor.text_edit),
            (self.answer_editor.text_edit, self.save_button),
            (self.save_button, self.reject_button),
            (self.reject_button, self.revert_button),
        ):
            QWidget.setTabOrder(before, after)
        self.reload()

    # --- Page interface -------------------------------------------------------

    def has_unsaved_changes(self) -> bool:
        return (
            self._current is not None and tuple(self._answers) != self._current.answers
        )

    def save(self) -> bool:
        return self.save_data()

    # --- Sheets ---------------------------------------------------------------

    def reload(self, select: str | None = None) -> None:
        """Refill the list of sheets, keeping (or moving to) a selection."""
        self._captures = list_captures(self._connection)
        keep = select or (self._current.capture_id if self._current else None)
        self.sheet_list.blockSignals(True)  # noqa: FBT003 (Qt API is positional)
        self.sheet_list.clear()
        for capture in self._captures:
            item = QListWidgetItem(status_text(capture))
            item.setData(Qt.ItemDataRole.UserRole, capture.capture_id)
            self.sheet_list.addItem(item)
        self.empty_note.setVisible(not self._captures)
        ids = [capture.capture_id for capture in self._captures]
        # The sheet is chosen here, not by the person: selecting it mustn't run
        # _on_sheet_chosen, which would ask about leaving the sheet shown.
        if keep in ids:
            self.sheet_list.setCurrentRow(ids.index(keep))
            shown = self._captures[ids.index(keep)]
        elif self._captures:
            self.sheet_list.setCurrentRow(0)
            shown = self._captures[0]
        else:
            shown = None
        self.sheet_list.blockSignals(False)  # noqa: FBT003
        self._show(shown)
        self._update_buttons()

    def add_images(self) -> None:
        """Add images: each is copied in, waiting to be read (wiki 60001-60002)."""
        paths = choose_images(self)
        if not paths:
            return
        added: list[Capture] = []
        duplicates: list[str] = []
        failed: list[str] = []
        for path in paths:
            try:
                added.append(add_capture(self._connection, path))
            except DuplicateCaptureError:
                duplicates.append(path.name)
            except OSError:
                failed.append(path.name)
        self.reload(select=added[0].capture_id if added else None)
        messages = []
        if added:
            messages.append(
                tr(
                    "Added %n image(s). Read waiting sheets reads them.",
                    None,
                    len(added),
                )
            )
        if duplicates:
            messages.append(
                tr("Already added, so skipped: {files}.").format(
                    files=", ".join(duplicates)
                )
            )
        if failed:
            messages.append(
                tr("Couldn't open: {files}.").format(files=", ".join(failed))
            )
        self.status_message.emit(" ".join(messages))

    def read_waiting(self) -> None:
        """Read every sheet waiting to be read, showing progress (wiki 60003)."""
        waiting = [
            capture
            for capture in self._captures
            if capture.status == CAPTURE_STATUSES.WAITING
        ]
        if not waiting:
            self.status_message.emit(tr("No sheets are waiting to be read."))
            return
        organization = load_organization(self._connection)
        paper_size = organization.paper_size if organization else PAPER_SIZES.LETTER
        progress = QProgressDialog(
            tr("Reading sheets…"), tr("Stop"), 0, len(waiting), self
        )
        progress.setWindowTitle(tr("Reading sheets"))
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        results = []
        for number, capture in enumerate(waiting):
            if progress.wasCanceled():
                break
            progress.setLabelText(
                tr("Reading {file} ({number} of {count})…").format(
                    file=capture.original_name, number=number + 1, count=len(waiting)
                )
            )
            progress.setValue(number)
            results.append(read_capture(self._connection, capture, paper_size))
        progress.setValue(len(waiting))
        read = [
            capture for capture in results if capture.status == CAPTURE_STATUSES.READ
        ]
        first_to_check = read[0].capture_id if read else None
        self.reload(select=first_to_check)
        unreadable = len(results) - len(read)
        message = tr("Read %n sheet(s).", None, len(read))
        # Against the list reload just loaded, rather than loading it again for
        # every sheet read.
        alike = sum(
            1
            for capture in read
            if any(capture.looks_like(other) for other in self._captures)
        )
        if alike:
            message += " " + tr(
                "%n may show the same sheet as another picture; choose one to "
                "see which.",
                None,
                alike,
            )
        if unreadable:
            message += " " + tr(
                "%n couldn't be read; choose one to see why.", None, unreadable
            )
        self.status_message.emit(message)

    def export_data(self) -> None:
        """Export a form's checked sheets as CSV files or a JSON file."""
        counts = saved_sheet_counts(self._connection)
        forms = [
            (form, counts[form.form_id])
            for form in list_forms(self._connection)
            if counts.get(form.form_id)
        ]
        by_id = {form.form_id: form for form, _ in forms}
        chosen = choose_export(
            self,
            forms,
            self._sheet_choices(forms),
            lambda form_id: self.edit_export_names(by_id[form_id]),
            lambda form_id, combine: mixed_layout_warning(
                collect(self._connection, by_id[form_id], combine)
            ),
        )
        if chosen is None:
            return
        form_id, file_format, combine, latest_values = chosen
        form = by_id[form_id]
        names = load_export_names(self._connection, form.form_id)
        data = collect(self._connection, form, combine, latest_values=latest_values)
        path = choose_export_path(
            self, file_format, self._export_folder / default_file_name(form)
        )
        if path is None:
            return
        self._export_folder = path.parent
        try:
            if file_format == CSV_FORMAT:
                # The save dialog asked about the file named; not the others.
                beside = [
                    other for other in csv_paths(data, path)[1:] if other.exists()
                ]
                if not confirm_replacing(self, beside):
                    return
                files = len(write_csv(data, path, names))
                where = str(path.parent)
            else:
                write_json(data, path, names)
                files, where = 1, str(path)
        except OSError as error:
            QMessageBox.warning(self, tr("Couldn't export the data"), str(error))
            return
        # Two counts, so two sentences: each gets its own plural form.
        self.status_message.emit(
            tr('Exported %n sheet(s) of "{form}".', None, data.sheet_count).format(
                form=form.name
            )
            + " "
            + tr("Wrote %n file(s) to {where}.", None, files).format(where=where)
        )

    def edit_export_names(self, form: Form) -> None:
        """Export data > Columns: choose and rename a form's exported columns."""
        names = choose_export_names(
            self,
            output_files(self._connection, form),
            load_export_names(self._connection, form.form_id),
        )
        if names is None:
            return
        save_export_names(self._connection, form.form_id, names)
        self.status_message.emit(
            tr('Saved the columns to export for "{form}".').format(form=form.name)
        )

    def _sheet_choices(
        self, forms: list[tuple[Form, int]]
    ) -> dict[str, list[tuple[str, str]]]:
        """Each form's checked sheets, described so the right ones can be picked.

        The description has the file, page, when it was captured, and the sheet
        details written on it.
        """
        wanted = {form.form_id for form, _ in forms}
        versions: dict[tuple[str, int], Form | None] = {}
        choices: dict[str, list[tuple[str, str]]] = {}
        for capture in self._captures:
            if (
                capture.status != CAPTURE_STATUSES.SAVED
                or capture.form_id not in wanted
                or capture.form_version is None
            ):
                continue
            key = (capture.form_id, capture.form_version)
            if key not in versions:
                versions[key] = load_form_version(self._connection, *key)
            description = tr("{file}: page {page}, captured {when}").format(
                file=capture.original_name,
                page=capture.page,
                when=capture.added_at[:16].replace("T", " "),
            )
            details = _details_summary(versions[key], capture)
            if details:
                description = f"{description} · {details}"
            choices.setdefault(capture.form_id, []).append(
                (capture.capture_id, description)
            )
        return choices

    def remove_sheet(self) -> None:
        capture = self._current
        if capture is None:
            return
        if not confirm_destructive(
            self,
            tr("Remove sheet"),
            tr(
                'Remove "{file}" and any data checked from it? This can\'t be undone.'
            ).format(file=capture.original_name),
            tr("Remove"),
        ):
            return
        row = self.sheet_list.currentRow()
        delete_capture(self._connection, capture)
        self._current = None
        self._answers = []
        remaining = [c for c in self._captures if c.capture_id != capture.capture_id]
        neighbour = remaining[min(row, len(remaining) - 1)] if remaining else None
        self.reload(select=neighbour.capture_id if neighbour else None)
        self.status_message.emit(
            tr('Removed "{file}".').format(file=capture.original_name)
        )

    # --- Checking (wiki 60004) ------------------------------------------------

    def save_data(self) -> bool:
        """Save the checked answers as the sheet's data; False if any are wrong."""
        capture = self._current
        if capture is None or capture.status in {
            CAPTURE_STATUSES.WAITING,
            CAPTURE_STATUSES.UNREADABLE,
        }:
            return True
        self._take_editor_values()
        problems = [
            (row, self._entry_error(answer))
            for row, answer in enumerate(self._answers)
            if self._entry_error(answer)
        ]
        self._fill_answers_table()
        if problems:
            first_row, _ = problems[0]
            self.answers_table.selectRow(first_row)
            self.answer_editor.current_editor.setFocus(Qt.FocusReason.OtherFocusReason)
            self.status_message.emit(
                tr("%n answer(s) to fix before saving.", None, len(problems))
            )
            return False
        saved = replace(
            capture, status=CAPTURE_STATUSES.SAVED, answers=tuple(self._answers)
        )
        save_capture(self._connection, saved)
        # Saved: nothing on it is unsaved now, so moving on asks nothing.
        self._current = saved
        self.reload(select=self._next_to_check(saved))
        self.status_message.emit(
            tr('Saved the data from "{file}".').format(file=capture.original_name)
        )
        return True

    def reject_sheet(self) -> None:
        """Keep the sheet but leave it out of the data (a spoilt or test sheet)."""
        capture = self._current
        if capture is None:
            return
        rejected = replace(capture, status=CAPTURE_STATUSES.REJECTED)
        save_capture(self._connection, rejected)
        self.reload(select=self._next_to_check(rejected))
        self.status_message.emit(
            tr('Rejected "{file}": it stays here, but its data isn\'t used.').format(
                file=capture.original_name
            )
        )

    def revert(self) -> None:
        """Put the answers back as they were last saved (or read)."""
        if self._current is not None:
            self._show(self._current)

    # --- Internals --------------------------------------------------------------

    def _build_sheets_box(self) -> QGroupBox:
        box = QGroupBox(tr("Sheets"))
        self.sheet_list = QListWidget()
        self.sheet_list.currentRowChanged.connect(self._on_sheet_chosen)
        list_label = QLabel(tr("S&heets"))
        list_label.setBuddy(self.sheet_list)
        self.empty_note = QLabel(
            tr("No sheets yet. Add images of filled-in sheets to start.")
        )
        self.empty_note.setWordWrap(True)
        self.add_button = QPushButton(tr("Add &images…"))
        self.add_button.clicked.connect(self.add_images)
        self.read_button = QPushButton(tr("Rea&d waiting sheets"))
        self.read_button.clicked.connect(self.read_waiting)
        self.remove_button = QPushButton(tr("Remo&ve sheet"))
        self.remove_button.clicked.connect(self.remove_sheet)
        self.export_button = QPushButton(tr("E&xport data…"))
        self.export_button.setToolTip(
            tr("Save a form's checked sheets as CSV files or a JSON file")
        )
        self.export_button.clicked.connect(self.export_data)
        # Missed corner markers are the usual reason a photo can't be read.
        self.photo_tip = QLabel(
            tr(
                "Tip: lay the sheet flat with all four corner dots in the picture. "
                "In dim light, turn on the camera's flash, or better, move "
                "somewhere brighter."
            )
        )
        self.photo_tip.setWordWrap(True)
        self.add_button.setAccessibleDescription(self.photo_tip.text())
        layout = QVBoxLayout(box)
        layout.addWidget(list_label)
        layout.addWidget(self.sheet_list)
        layout.addWidget(self.empty_note)
        layout.addWidget(self.add_button)
        layout.addWidget(self.photo_tip)
        for button in (self.read_button, self.remove_button, self.export_button):
            layout.addWidget(button)
        return box

    def _build_check_box(self) -> QGroupBox:
        self.check_box = QGroupBox(tr("Check the data"))
        self.sheet_note = QLabel()
        # It shows file and form names, which mustn't be read as HTML.
        self.sheet_note.setTextFormat(Qt.TextFormat.PlainText)
        self.sheet_note.setWordWrap(True)
        self.close_up = QLabel()
        self.close_up.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.close_up.setMinimumHeight(CLOSE_UP_HEIGHT)
        self.close_up.setAccessibleName(tr("Close-up of the answer on the sheet"))

        self.answers_table = QTableWidget(0, 3)
        self.answers_table.setHorizontalHeaderLabels(
            [tr("Answer"), tr("Value"), tr("Note")]
        )
        header = self.answers_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.answers_table.verticalHeader().setVisible(False)
        self.answers_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.answers_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.answers_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.answers_table.setTabKeyNavigation(False)
        self.answers_table.currentCellChanged.connect(self._on_answer_chosen)
        answers_label = QLabel(tr("Ans&wers"))
        answers_label.setBuddy(self.answers_table)

        self.editor_form = QFormLayout()
        # The label names the answer, which can be long: above its field.
        self.editor_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.answer_editor = AnswerEditor()
        self.answer_editor.changed.connect(self._on_value_edited)
        self.value_label, self.value_error = add_field_row(
            self.editor_form, tr("Va&lue"), self.answer_editor
        )

        self.save_button = QPushButton(tr("&Save data"))
        self.save_button.setToolTip(tr("Save the checked answers as data (Ctrl+S)"))
        self.save_button.clicked.connect(self.save_data)
        self.reject_button = QPushButton(tr("Re&ject sheet"))
        self.reject_button.setToolTip(
            tr("Keep the sheet but leave its answers out of the data")
        )
        self.reject_button.clicked.connect(self.reject_sheet)
        self.revert_button = QPushButton(tr("&Revert"))
        self.revert_button.setToolTip(tr("Undo changes since the answers were saved"))
        self.revert_button.clicked.connect(self.revert)
        buttons = QHBoxLayout()
        buttons.addStretch()
        for button in (self.revert_button, self.reject_button, self.save_button):
            buttons.addWidget(button)

        layout = QVBoxLayout(self.check_box)
        layout.addWidget(self.sheet_note)
        layout.addWidget(self.close_up)
        layout.addWidget(answers_label)
        layout.addWidget(self.answers_table, 1)
        layout.addLayout(self.editor_form)
        layout.addLayout(buttons)
        return self.check_box

    def _on_sheet_chosen(self, row: int) -> None:
        if not 0 <= row < len(self._captures):
            return
        chosen = self._captures[row]
        if self._current is not None and chosen.capture_id == self._current.capture_id:
            return
        if self.has_unsaved_changes():
            answer = ask_save_discard_cancel(
                self, tr("Save the data checked on this sheet first?")
            )
            if answer == QMessageBox.StandardButton.Cancel or (
                answer == QMessageBox.StandardButton.Save and not self.save_data()
            ):
                self._select_current()
                return
        self._show(chosen)

    def _select_current(self) -> None:
        ids = [capture.capture_id for capture in self._captures]
        if self._current is not None and self._current.capture_id in ids:
            self.sheet_list.blockSignals(True)  # noqa: FBT003
            self.sheet_list.setCurrentRow(ids.index(self._current.capture_id))
            self.sheet_list.blockSignals(False)  # noqa: FBT003

    def _show(self, capture: Capture | None) -> None:
        """Show a sheet: its image, and its answers to check."""
        self._current = capture
        self._answers = list(capture.answers) if capture else []
        # The editor's values belong to the sheet shown before: never copy them.
        self._editing_row = None
        self._form = None
        self._template = None
        if capture is None:
            self.sheet_canvas.show_image(None, "")
            self.sheet_note.setText("")
        elif capture.status in {CAPTURE_STATUSES.WAITING, CAPTURE_STATUSES.UNREADABLE}:
            self.sheet_canvas.show_image(
                image_path(self._connection, capture),
                tr("The image as added: {file}.").format(file=capture.original_name),
            )
            self.sheet_note.setText(
                capture.problem
                if capture.status == CAPTURE_STATUSES.UNREADABLE
                else tr("Not read yet: use Read waiting sheets.")
            )
        else:
            self._load_page(capture)
        self.sheet_canvas.set_current(None)
        self.sheet_canvas.set_answers(self._canvas_answers())
        self._fill_answers_table()
        if self._answers:
            self.answers_table.selectRow(0)
        else:
            self._show_answer(None)
        self._update_buttons()

    def _load_page(self, capture: Capture) -> None:
        if capture.form_id is not None and capture.form_version is not None:
            self._form = load_form_version(
                self._connection, capture.form_id, capture.form_version
            )
            stored = load_printed_layout(
                self._connection, capture.form_id, capture.form_version
            )
            if stored is not None and capture.page is not None:
                pages = stored["pages"]
                if 1 <= capture.page <= len(pages):
                    self._template = self._with_writing_areas(
                        PageTemplate.from_dict(pages[capture.page - 1]), capture.page
                    )
        page_image = page_image_path(self._connection, capture)
        form_name = self._form.name if self._form else ""
        self.sheet_canvas.show_image(
            page_image
            if page_image.exists()
            else image_path(self._connection, capture),
            tr(
                "Page {page} of {form}, straightened. Tab goes from answer to "
                "answer; type in handwritten ones, and press 1 to 9 to choose a "
                "bubble."
            ).format(page=capture.page, form=form_name),
        )
        notes = {
            CAPTURE_STATUSES.READ: tr(
                "Page {page} of {form}, version {version}. Check each answer against "
                "the sheet, type in what's handwritten, then Save data."
            ),
            CAPTURE_STATUSES.SAVED: tr(
                "Page {page} of {form}, version {version}. Saved as data; changes "
                "can still be saved."
            ),
            CAPTURE_STATUSES.REJECTED: tr(
                "Page {page} of {form}, version {version}. Rejected: its answers "
                "aren't used. Save data to use them after all."
            ),
        }
        note = notes[capture.status].format(
            page=capture.page, form=form_name, version=capture.form_version
        )
        warning = duplicate_warning(likely_duplicates(self._connection, capture))
        self.sheet_note.setText(note + " " + warning if warning else note)

    def _fill_answers_table(self) -> None:
        row = self.answers_table.currentRow()
        self.answers_table.blockSignals(True)  # noqa: FBT003
        self.answers_table.setRowCount(len(self._answers))
        band = band_color(self.answers_table.palette())
        for index, answer in enumerate(self._answers):
            error = self._entry_error(answer)
            note = error or answer.problem
            if not note and self._is_written(answer) and not answer.values:
                note = tr("Handwritten: type it in")
            spec = self._spec(answer)
            if not note and spec is not None and answer.changed_by_hand(spec):
                read = ", ".join(self._labels(answer, answer.scanned)) or tr("nothing")
                note = tr("Changed by hand; the sheet read: {values}").format(
                    values=read
                )
            # Every other table row's answers shaded, to tell rows apart.
            banded = answer.table_row is not None and answer.table_row % 2 == 1
            for column, text in (
                (NAME_COLUMN, self._short_answer_name(answer)),
                (VALUE_COLUMN, ", ".join(self._value_labels(answer))),
                (NOTE_COLUMN, note),
            ):
                item = QTableWidgetItem(text)
                if column == NAME_COLUMN:
                    # The short name shows; the whole one is read out.
                    full_name = self._answer_name(answer)
                    item.setData(Qt.ItemDataRole.AccessibleTextRole, full_name)
                    item.setToolTip(full_name)
                if banded:
                    item.setBackground(band)
                self.answers_table.setItem(index, column, item)
        self.answers_table.blockSignals(False)  # noqa: FBT003
        if 0 <= row < len(self._answers):
            self.answers_table.setCurrentCell(row, NAME_COLUMN)

    def _on_answer_chosen(self, row: int, *_: int) -> None:
        self._take_editor_values()
        self._show_answer(row if 0 <= row < len(self._answers) else None)

    def _show_answer(self, row: int | None) -> None:
        """Show one answer: outlined on the page, in close-up and in the editor."""
        self._editing_row = row
        answer = self._answers[row] if row is not None else None
        spec = self._spec(answer) if answer is not None else None
        self.answer_editor.setEnabled(spec is not None)
        if answer is None or spec is None:
            self._follow_on_canvas(None)
            self.close_up.clear()
            set_field_error(self.editor_form, self.answer_editor, self.value_error, "")
            return
        self.value_label.setText(
            tr("Va&lue of {answer}").format(answer=self._answer_name(answer))
        )
        self.answer_editor.set_answer(spec, answer.values)
        self.value_label.setBuddy(self.answer_editor.current_editor)
        region = self._region(answer)
        self._follow_on_canvas(row)
        close_up = self.sheet_canvas.close_up(region) if region else QPixmap()
        if close_up.isNull():
            self.close_up.clear()
        else:
            self.close_up.setPixmap(
                close_up.scaled(
                    self.close_up.width(),
                    CLOSE_UP_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self.close_up.setAccessibleDescription(
            tr("Close-up of {answer} on the sheet.").format(
                answer=self._answer_name(answer)
            )
        )
        set_field_error(
            self.editor_form,
            self.answer_editor.current_editor,
            self.value_error,
            self._entry_error(answer) or answer.problem,
        )

    def _on_value_edited(self) -> None:
        self._take_editor_values()
        self._fill_answers_table()
        row = self._editing_row
        if row is not None:
            answer = self._answers[row]
            set_field_error(
                self.editor_form,
                self.answer_editor.current_editor,
                self.value_error,
                self._entry_error(answer),
            )
        self._update_buttons()

    def _take_editor_values(self) -> None:
        """Copy the editor's values into the answer it is showing."""
        row = self._editing_row
        if row is None or not 0 <= row < len(self._answers):
            return
        values = self.answer_editor.values()
        answer = self._answers[row]
        if values != answer.values:
            self._answers[row] = replace(answer, values=values, problem="")
            self.sheet_canvas.update_answer(row, self._canvas_answer(row))

    # --- The sheet: typing and marking on it -------------------------------------

    def _build_sheet_view(self) -> QScrollArea:
        self.sheet_canvas = SheetCanvas()
        self.sheet_canvas.current_changed.connect(self._on_canvas_current)
        self.sheet_canvas.values_edited.connect(self._on_canvas_values)
        self.sheet_scroll = QScrollArea()
        self.sheet_scroll.setWidget(self.sheet_canvas)
        self.sheet_scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        # Not a Tab stop of its own: Tab goes to the sheet's answers inside it.
        self.sheet_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sheet_scroll.viewport().installEventFilter(self)
        return self.sheet_scroll

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt override)
        # The page fits the width it's shown in, so it reads well at any size.
        if (
            watched is self.sheet_scroll.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self.sheet_canvas.set_fit_width(self.sheet_scroll.viewport().width())
        return super().eventFilter(watched, event)

    def _canvas_answers(self) -> list[CanvasAnswer]:
        return [self._canvas_answer(row) for row in range(len(self._answers))]

    def _canvas_answer(self, row: int) -> CanvasAnswer:
        """One answer as the sheet draws it, with its place and bubbles."""
        answer = self._answers[row]
        spec = self._spec(answer)
        region = self._region_of(answer)
        if spec is None:
            return CanvasAnswer(
                name=self._answer_name(answer),
                answer_type=ANSWER_TYPES.WRITTEN,
                rect=region.rect if region else (0, 0, 0, 0),
                entry=region.writing if region else None,
            )
        printed = spec.printed_choices()
        return CanvasAnswer(
            name=self._answer_name(answer),
            answer_type=spec.answer_type,
            rect=region.rect if region else (0, 0, 0, 0),
            bubbles=region.bubbles if region else (),
            entry=region.writing if region else None,
            entry_cells=typing_cells(spec),
            entry_hint=typing_hint(spec),
            choices=tuple((choice.output, choice.label) for choice in printed),
            empty_value=(
                spec.choices[1].output
                if spec.answer_type == ANSWER_TYPES.YES_NO and len(spec.choices) > 1
                else ""
            ),
            values=answer.values,
            problem=self._entry_error(answer) or answer.problem,
        )

    def _follow_on_canvas(self, row: int | None) -> None:
        """Show the list's current answer on the sheet, scrolled into view."""
        if self._syncing:
            return
        self._syncing = True
        try:
            self.sheet_canvas.set_current(row)
        finally:
            self._syncing = False
        if row is not None:
            area = self.sheet_canvas.answer_rect_in_view(row)
            self.sheet_scroll.ensureVisible(
                area.center().x(), area.center().y(), area.width() // 2 + 20, 60
            )

    def _on_canvas_current(self, row: int) -> None:
        """An answer chosen on the sheet: the list, close-up and editor follow."""
        if self._syncing:
            return
        self._syncing = True
        try:
            self.answers_table.selectRow(row)
        finally:
            self._syncing = False
        area = self.sheet_canvas.answer_rect_in_view(row)
        self.sheet_scroll.ensureVisible(
            area.center().x(), area.center().y(), area.width() // 2 + 20, 60
        )
        answer = self._answers[row]
        values = ", ".join(self._value_labels(answer)) or tr("nothing")
        canvas_answer = self.sheet_canvas.answer(row)
        hint = (
            ""
            if canvas_answer.written
            else tr("Press 1 to %n to choose.", None, len(canvas_answer.choices))
        )
        message = tr("{answer}: {value}.").format(
            answer=self._answer_name(answer), value=values
        )
        self.sheet_canvas.setAccessibleDescription(f"{message} {hint}".strip())
        announce(self.sheet_canvas, f"{message} {hint}".strip())

    def _on_canvas_values(self, row: int, values: tuple[str, ...]) -> None:
        """Typed or marked on the sheet: store it, and show it everywhere."""
        if not 0 <= row < len(self._answers):
            return
        answer = self._answers[row]
        if values == answer.values:
            return
        self._answers[row] = replace(answer, values=values, problem="")
        self.sheet_canvas.update_answer(row, self._canvas_answer(row))
        self._fill_answers_table()
        if row == self._editing_row:
            spec = self._spec(self._answers[row])
            if spec is not None:
                self.answer_editor.set_answer(spec, values)
            set_field_error(
                self.editor_form,
                self.answer_editor.current_editor,
                self.value_error,
                self._entry_error(self._answers[row]),
            )
        self._update_buttons()

    def _update_buttons(self) -> None:
        checkable = self._current is not None and self._current.status in {
            CAPTURE_STATUSES.READ,
            CAPTURE_STATUSES.SAVED,
            CAPTURE_STATUSES.REJECTED,
        }
        self.save_button.setEnabled(checkable)
        self.reject_button.setEnabled(
            checkable
            and self._current is not None
            and self._current.status != CAPTURE_STATUSES.REJECTED
        )
        self.revert_button.setEnabled(self.has_unsaved_changes())
        self.remove_button.setEnabled(self._current is not None)
        self.read_button.setEnabled(
            any(c.status == CAPTURE_STATUSES.WAITING for c in self._captures)
        )

    def _next_to_check(self, after: Capture) -> str:
        """The next sheet read but not yet checked, else ``after`` itself."""
        ids = [capture.capture_id for capture in self._captures]
        start = ids.index(after.capture_id) if after.capture_id in ids else 0
        for capture in [*self._captures[start + 1 :], *self._captures[:start]]:
            if capture.status == CAPTURE_STATUSES.READ:
                return capture.capture_id
        return after.capture_id

    def _spec(self, answer: CapturedAnswer) -> AnswerSpec | None:
        if self._form is None or not 0 <= answer.block_index < len(self._form.blocks):
            return None
        content = self._form.blocks[answer.block_index].content
        if isinstance(content, TableBlock) and answer.column is not None:
            return content.columns[answer.column].answer
        if isinstance(content, SheetDetails) and answer.column is not None:
            return content.fields[answer.column].answer
        if isinstance(content, Question):
            return content.answer
        return None

    def _is_written(self, answer: CapturedAnswer) -> bool:
        spec = self._spec(answer)
        return spec is not None and not spec.choices

    def _entry_error(self, answer: CapturedAnswer) -> str:
        spec = self._spec(answer)
        return spec.entry_error(answer.values) if spec is not None else ""

    def _answer_name(self, answer: CapturedAnswer) -> str:
        if self._form is None or not 0 <= answer.block_index < len(self._form.blocks):
            return ""
        content = self._form.blocks[answer.block_index].content
        if (
            isinstance(content, TableBlock)
            and answer.column is not None
            and answer.table_row is not None
        ):
            return tr("{table}, row {row}, {column}").format(
                table=content.name,
                row=answer.table_row + 1,
                column=content.columns[answer.column].name,
            )
        if isinstance(content, SheetDetails) and answer.column is not None:
            return content.fields[answer.column].name
        return content.name

    def _short_answer_name(self, answer: CapturedAnswer) -> str:
        """A table answer by its column's name alone; others as ``_answer_name``.

        The list shows its row by shading, and the sheet by its outline.
        """
        if self._form is not None and 0 <= answer.block_index < len(self._form.blocks):
            content = self._form.blocks[answer.block_index].content
            if isinstance(content, TableBlock) and answer.column is not None:
                return content.columns[answer.column].name
        return self._answer_name(answer)

    def _value_labels(self, answer: CapturedAnswer) -> list[str]:
        """The answer's values as printed on the sheet (choice labels)."""
        return self._labels(answer, answer.values)

    def _labels(self, answer: CapturedAnswer, values: tuple[str, ...]) -> list[str]:
        spec = self._spec(answer)
        if spec is None or not spec.choices:
            return list(values)
        labels = {choice.output: choice.label for choice in spec.choices}
        return [labels.get(value, value) for value in values]

    def _with_writing_areas(self, stored: PageTemplate, page: int) -> PageTemplate:
        """``stored``, with where to type for pages printed before that was kept."""
        if self._form is None or all(
            region.writing is not None for region in stored.regions
        ):
            return stored
        organization = load_organization(self._connection)
        paper_size = organization.paper_size if organization else PAPER_SIZES.LETTER
        layout = layout_form(self._form, paper_size)
        if not 1 <= page <= len(layout.pages):
            return stored
        return with_writing_areas(stored, page_template(layout, layout.pages[page - 1]))

    def _region(self, answer: CapturedAnswer) -> tuple[int, int, int, int] | None:
        region = self._region_of(answer)
        return region.rect if region is not None else None

    def _region_of(self, answer: CapturedAnswer) -> AnswerRegion | None:
        if self._template is None:
            return None
        return next(
            (region for region in self._template.regions if region.key == answer.key),
            None,
        )

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.PaletteChange:
            style_error_label(self.value_error, self.palette())
            # Re-shade the bands for the new theme.
            self._fill_answers_table()
        super().changeEvent(event)
