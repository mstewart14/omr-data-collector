"""The scanner folder: scans saved into a folder, added and read (wiki 60011-60015)."""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from omr_data_collector.constants import CAPTURE_STATUSES
from omr_data_collector.rendering.page_photo import save_as_pdf
from omr_data_collector.scanner_folder import (
    DEFAULT_CHECK_MINUTES,
    SETTLE_SECONDS,
    FolderCheck,
    ScannerSettings,
    check_folder,
    check_summary,
    files_to_take,
    load_scanner_settings,
    move_aside,
    save_scanner_settings,
)
from omr_data_collector.storage.capture_store import add_capture, list_captures
from omr_data_collector.ui.CapturePage import CapturePage
from omr_data_collector.ui.MainWindow import MainWindow
from omr_data_collector.ui.scanner_watch import ScannerWatch
from omr_data_collector.ui.ScannerFolderDialog import ScannerFolderDialog
from tests.sheets import LETTER, Sheet

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from pytest_mock import MockerFixture
    from pytestqt.qtbot import QtBot

    from omr_data_collector.layout.form_layout import FormLayout
    from omr_data_collector.models.Form import Form
    from omr_data_collector.models.Organization import Organization

pytestmark = pytest.mark.usefixtures("qapp")

AN_HOUR = 3600


def settled(path: Path) -> Path:
    """As if the scanner finished saving ``path`` an hour ago."""
    then = time.time() - AN_HOUR
    os.utime(path, (then, then))
    return path


@pytest.fixture
def pictures(
    organization: Organization, printed_form: tuple[Form, FormLayout], tmp_path: Path
) -> tuple[Path, Path]:
    """Photos of two filled-in intake sheets, outside the scanner folder."""
    form, layout = printed_form
    first = Sheet(form, organization, layout)
    first.fill_question(1, 0, 3)
    second = Sheet(form, organization, layout)
    second.fill_cell(2, row=0, column=2, choice=1)
    return (
        first.photograph(tmp_path / "pictures" / "first.jpg"),
        second.photograph(tmp_path / "pictures" / "second.jpg"),
    )


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    scans = tmp_path / "scanner"
    scans.mkdir()
    return scans


def drop(folder: Path, name: str, content: bytes) -> Path:
    """The scanner saves a file into the folder, and finishes."""
    path = folder / name
    path.write_bytes(content)
    return settled(path)


# --- Settings (wiki 60011) ---------------------------------------------------------


def test_scanner_settings_start_off_reading_every_ten_minutes() -> None:
    settings = load_scanner_settings()

    assert settings == ScannerSettings()
    assert not settings.enabled
    assert settings.check_minutes == DEFAULT_CHECK_MINUTES == 10
    assert settings.read_automatically


def test_scanner_settings_are_kept(folder: Path) -> None:
    chosen = ScannerSettings(str(folder), check_minutes=3, read_automatically=False)

    save_scanner_settings(chosen)

    assert load_scanner_settings() == chosen


def test_the_dialog_refuses_a_folder_that_doesnt_exist(
    qtbot: QtBot, folder: Path
) -> None:
    dialog = ScannerFolderDialog(None, ScannerSettings())
    qtbot.addWidget(dialog)
    dialog.folder_edit.setText(str(folder / "missing"))

    dialog.accept()

    assert dialog.result() != ScannerFolderDialog.DialogCode.Accepted
    assert "There's no folder" in dialog.folder_edit.accessibleDescription()

    dialog.folder_edit.setText(f" {folder} ")
    dialog.minutes_spin.setValue(5)
    dialog.read_check.setChecked(False)
    dialog.accept()

    assert dialog.result() == ScannerFolderDialog.DialogCode.Accepted
    assert dialog.chosen_settings() == ScannerSettings(
        str(folder), 5, read_automatically=False
    )


# --- Which files are taken (wiki 60012-60013) -------------------------------------


def test_only_finished_scans_at_the_top_of_the_folder_are_taken(folder: Path) -> None:
    photo = drop(folder, "photo.JPG", b"jpeg")
    scan = drop(folder, "scan.pdf", b"pdf")
    drop(folder, "notes.txt", b"not a scan")
    drop(folder, ".scan.pdf.part", b"being saved")
    (folder / "Added").mkdir()
    drop(folder / "Added", "old.jpg", b"jpeg")
    (folder / "saving.pdf").write_bytes(b"still being written")

    ready, saving = files_to_take(folder)

    assert ready == [photo, scan]
    assert saving == 1
    later = time.time() + SETTLE_SECONDS + 1
    assert len(files_to_take(folder, later)[0]) == 3


def test_a_file_moved_aside_never_replaces_one_there(folder: Path) -> None:
    when = datetime(2026, 11, 11, 14, 5, 9).astimezone()
    first = move_aside(drop(folder, "scan.pdf", b"1"), "Added", when)
    second = move_aside(drop(folder, "scan.pdf", b"2"), "Added", when)
    third = move_aside(drop(folder, "scan.pdf", b"3"), "Added", when)

    assert first == folder / "Added" / "scan.pdf"
    assert second == folder / "Added" / "scan 2026-11-11 14.05.09.pdf"
    assert third == folder / "Added" / "scan 2026-11-11 14.05.09 (2).pdf"
    assert [path.read_bytes() for path in (first, second, third)] == [b"1", b"2", b"3"]
    assert not (folder / "scan.pdf").exists()


# --- Adding and reading (wiki 60012, 60014, 60015) ---------------------------------


def test_new_scans_are_added_read_and_moved_to_added(
    connection: sqlite3.Connection, folder: Path, pictures: tuple[Path, Path]
) -> None:
    first, second = pictures
    drop(folder, "photo.jpg", first.read_bytes())
    settled(save_as_pdf(folder / "scan.pdf", first, second))
    drop(folder, "notes.txt", b"not a scan")

    result = check_folder(connection, ScannerSettings(str(folder)))

    # The PDF's first page shows the photo's sheet, but drawn afresh, so it's
    # a picture of its own (the Capture page warns that they look alike).
    assert [capture.original_name for capture in result.added] == [
        "photo.jpg",
        "scan.pdf, page 1",
        "scan.pdf, page 2",
    ]
    assert result.duplicates == []
    assert (result.read, result.unreadable) == (3, 0)
    assert all(c.status == CAPTURE_STATUSES.READ for c in list_captures(connection))
    assert sorted(path.name for path in (folder / "Added").iterdir()) == [
        "photo.jpg",
        "scan.pdf",
    ]
    assert sorted(path.name for path in folder.iterdir()) == ["Added", "notes.txt"]
    assert check_summary(result, asked=False) == (
        "Added 3 sheets from the scanner folder. Read 3 of them."
    )


def test_scans_can_be_left_waiting_to_be_read(
    connection: sqlite3.Connection, folder: Path, pictures: tuple[Path, Path]
) -> None:
    drop(folder, "photo.jpg", pictures[0].read_bytes())

    result = check_folder(
        connection, ScannerSettings(str(folder), read_automatically=False)
    )

    (capture,) = result.added
    assert capture.status == CAPTURE_STATUSES.WAITING
    assert result.read == 0


def test_a_scan_added_before_is_moved_to_added_too(
    connection: sqlite3.Connection, folder: Path, pictures: tuple[Path, Path]
) -> None:
    add_capture(connection, pictures[0])
    drop(folder, "again.jpg", pictures[0].read_bytes())

    result = check_folder(connection, ScannerSettings(str(folder)))

    assert result.added == []
    assert result.duplicates == ["again.jpg"]
    assert (folder / "Added" / "again.jpg").exists()
    assert len(list_captures(connection)) == 1


def test_files_that_cant_be_added_are_set_aside(
    connection: sqlite3.Connection, folder: Path
) -> None:
    drop(folder, "broken.pdf", b"not a PDF")
    drop(folder, "broken.jpg", b"not a picture")

    result = check_folder(connection, ScannerSettings(str(folder)))

    assert sorted(result.failed) == ["broken.jpg", "broken.pdf"]
    assert list_captures(connection) == []
    assert sorted(path.name for path in (folder / "Couldn't add").iterdir()) == [
        "broken.jpg",
        "broken.pdf",
    ]
    assert check_summary(result, asked=False) == (
        "Couldn't add broken.jpg, broken.pdf: moved to the scanner folder's "
        '"Couldn\'t add" folder.'
    )

    assert check_folder(connection, ScannerSettings(str(folder))).failed == []


def test_a_folder_that_cant_be_reached_is_reported(
    connection: sqlite3.Connection, folder: Path
) -> None:
    result = check_folder(connection, ScannerSettings(str(folder / "offline")))

    assert "Couldn't open the scanner folder" in check_summary(result, asked=False)


def test_a_check_stops_when_the_app_closes(
    connection: sqlite3.Connection, folder: Path, pictures: tuple[Path, Path]
) -> None:
    drop(folder, "photo.jpg", pictures[0].read_bytes())

    result = check_folder(
        connection, ScannerSettings(str(folder)), should_stop=lambda: True
    )

    assert result.added == []
    assert (folder / "photo.jpg").exists()


def test_only_an_asked_for_check_reports_finding_nothing() -> None:
    assert check_summary(FolderCheck(), asked=False) == ""
    assert check_summary(FolderCheck(), asked=True) == (
        "No new scans in the scanner folder."
    )
    assert check_summary(FolderCheck(still_saving=1), asked=False) == ""
    assert check_summary(FolderCheck(still_saving=2), asked=True) == (
        "2 scans may still be being saved; they will be added in a minute or so."
    )


# --- Checking while the app is open (wiki 60012) -----------------------------------


def test_the_watch_checks_on_a_thread_and_reports_back(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    folder: Path,
    pictures: tuple[Path, Path],
) -> None:
    drop(folder, "photo.jpg", pictures[0].read_bytes())
    watch = ScannerWatch(connection)
    watch.apply(ScannerSettings(str(folder)), first_check_ms=60_000)

    with qtbot.waitSignal(watch.checked, timeout=60_000) as signal:
        assert watch.check_now() == ""
        assert watch.check_now() == "The scanner folder is being checked already."

    assert signal.args is not None
    result, asked = signal.args
    assert asked
    assert [capture.original_name for capture in result.added] == ["photo.jpg"]
    assert not watch.is_checking
    assert list_captures(connection)[0].status == CAPTURE_STATUSES.READ
    watch.stop()


def test_the_watch_says_when_no_folder_is_chosen(
    connection: sqlite3.Connection,
) -> None:
    watch = ScannerWatch(connection)

    watch.start()

    assert watch.check_now() == (
        "No scanner folder is chosen: choose one in Preferences."
    )


def test_refreshing_keeps_the_sheet_being_checked(
    qtbot: QtBot, connection: sqlite3.Connection, pictures: tuple[Path, Path]
) -> None:
    from omr_data_collector.engine.reading import read_capture  # noqa: PLC0415

    read_capture(connection, add_capture(connection, pictures[0]), LETTER)
    page = CapturePage(connection)
    qtbot.addWidget(page)
    # The first row's time, typed in from the handwriting.
    page.answers_table.selectRow(
        [answer.key for answer in page._answers].index((2, 0, 0))  # noqa: SLF001
    )
    page.answer_editor.text_edit.setText("09:30")
    page.answer_editor.text_edit.textEdited.emit("09:30")
    assert page.has_unsaved_changes()
    typed = list(page._answers)  # noqa: SLF001 (what the person has typed)

    # Meanwhile the scanner folder adds and reads another.
    read_capture(connection, add_capture(connection, pictures[1]), LETTER)
    page.refresh_sheets()

    assert page.sheet_list.count() == 2
    assert page.sheet_list.currentRow() == 0
    assert page.has_unsaved_changes()
    assert page._answers == typed  # noqa: SLF001


def test_choosing_a_scanner_folder_starts_watching_it(
    qtbot: QtBot,
    connection: sqlite3.Connection,
    mocker: MockerFixture,
    folder: Path,
) -> None:
    window = MainWindow(connection)
    qtbot.addWidget(window)
    chosen = ScannerSettings(str(folder), check_minutes=5)
    mocker.patch(
        "omr_data_collector.ui.MainWindow.choose_scanner_settings",
        return_value=chosen,
    )
    statuses: list[str] = []
    mocker.patch.object(window, "show_status", side_effect=statuses.append)

    with qtbot.waitSignal(window.scanner_watch.checked, timeout=60_000):
        window.change_scanner_folder()

    assert load_scanner_settings() == chosen
    assert window.scanner_watch.settings == chosen
    assert window.capture_page.check_scanner_button.isVisibleTo(window.capture_page)
    assert str(folder) in window.capture_page.scanner_note.text()
    assert statuses[0] == (
        f"Scans saved in {folder} will be added every 5 minutes while the app is open."
    )
    window.scanner_watch.stop()


def test_refreshing_shows_a_sheet_read_meanwhile(
    qtbot: QtBot, connection: sqlite3.Connection, pictures: tuple[Path, Path]
) -> None:
    from omr_data_collector.engine.reading import read_capture  # noqa: PLC0415

    waiting = add_capture(connection, pictures[0])
    page = CapturePage(connection)
    qtbot.addWidget(page)
    assert page.sheet_list.item(0).text() == "first.jpg: waiting to be read"

    read_capture(connection, waiting, LETTER)
    page.refresh_sheets()

    assert page.sheet_list.item(0).text() == "first.jpg: read, to check"
    assert page.answers_table.rowCount() > 0
