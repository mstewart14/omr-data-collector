"""The scanner folder: scans a scanner saves into a folder, added as sheets.

Wiki 60011-60015. While the app is open, the folder is checked every few
minutes (``ui/scanner_watch.py`` runs the checks, on a thread of their own).
Each check takes the pictures and PDFs at the top of the folder that the
scanner has finished saving, adds them as sheets waiting to be read (reading
them too, if chosen), and moves each file into the folder's "Added" folder so
it isn't taken again, or into "Couldn't add" if it can't be added, so it isn't
tried at every check. One computer watches each folder.

Nothing here imports the scanning engine at module level: the main window
imports this module, and the engine loads after the window opens.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import cv2

from omr_data_collector.constants import CAPTURE_STATUSES
from omr_data_collector.i18n import preferences, tr
from omr_data_collector.models.Organization import paper_size_of
from omr_data_collector.storage.capture_store import (
    DuplicateCaptureError,
    add_capture,
)
from omr_data_collector.storage.organization_store import load_organization
from omr_data_collector.storage.pdf_pages import (
    PdfError,
    images_to_add,
    is_pdf,
    is_scan,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from omr_data_collector.models.Capture import Capture

FOLDER_SETTING = "scannerFolder/folder"
CHECK_MINUTES_SETTING = "scannerFolder/checkMinutes"
READ_SETTING = "scannerFolder/readAutomatically"
DEFAULT_CHECK_MINUTES = 10
MIN_CHECK_MINUTES = 1
MAX_CHECK_MINUTES = 60
# A file is taken once it hasn't changed for this long: a scanner saving a long
# PDF to a network folder writes it bit by bit.
SETTLE_SECONDS = 60
# How far ahead a file's time may be before it's taken to be wrong.
CLOCK_SLACK_SECONDS = 60


@dataclass(frozen=True)
class ScannerSettings:
    """Preferences > Scanner folder, kept for this person on this computer."""

    folder: str = ""
    check_minutes: int = DEFAULT_CHECK_MINUTES
    read_automatically: bool = True

    @property
    def enabled(self) -> bool:
        return bool(self.folder)


def load_scanner_settings() -> ScannerSettings:
    settings = preferences()
    folder = settings.value(FOLDER_SETTING, "")
    # An INI file gives every value back as text.
    stored_minutes = str(settings.value(CHECK_MINUTES_SETTING, DEFAULT_CHECK_MINUTES))
    read = str(settings.value(READ_SETTING, "true")).lower()
    minutes = int(stored_minutes) if stored_minutes.isdigit() else DEFAULT_CHECK_MINUTES
    return ScannerSettings(
        folder=folder if isinstance(folder, str) else "",
        check_minutes=min(max(minutes, MIN_CHECK_MINUTES), MAX_CHECK_MINUTES),
        read_automatically=read not in {"false", "0"},
    )


def save_scanner_settings(chosen: ScannerSettings) -> None:
    settings = preferences()
    settings.setValue(FOLDER_SETTING, chosen.folder)
    settings.setValue(CHECK_MINUTES_SETTING, chosen.check_minutes)
    settings.setValue(READ_SETTING, chosen.read_automatically)
    settings.sync()


def added_folder_name() -> str:
    return tr("Added", "the scanner folder's folder for files added to the app")


def failed_folder_name() -> str:
    return tr(
        "Couldn't add", "the scanner folder's folder for files that couldn't be added"
    )


@dataclass
class FolderCheck:
    """What one check of the scanner folder did."""

    added: list[Capture] = field(default_factory=list)
    read: int = 0
    unreadable: int = 0
    # Files already in the app, and files that couldn't be added: names.
    duplicates: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    # Files the scanner may still be saving, left for a later check.
    still_saving: int = 0
    # Why the folder, or a file in it, couldn't be dealt with.
    problems: list[str] = field(default_factory=list)


def files_to_take(folder: Path, now: float | None = None) -> tuple[list[Path], int]:
    """The pictures and PDFs ready to take from ``folder``, and how many aren't yet.

    Only the folder's own files count, not those in folders inside it (Added
    and Couldn't add among them), nor hidden files, which scanners and network
    shares use while saving. A file changed less than SETTLE_SECONDS ago may
    still be being saved.

    Raises:
        OSError: The folder couldn't be read.
    """
    now = time.time() if now is None else now
    ready: list[Path] = []
    saving = 0
    for path in sorted(folder.iterdir()):
        if path.name.startswith(".") or not is_scan(path) or not path.is_file():
            continue
        if now - last_changed(path, now) < SETTLE_SECONDS:
            saving += 1
        else:
            ready.append(path)
    return ready, saving


def last_changed(path: Path, now: float) -> float:
    """When ``path`` last changed, as far as can be told.

    Unzipped and copied files keep the time they were changed elsewhere, and
    another computer's clock, or a zip's lack of time zones, can put that time
    hours ahead. Such a file would never seem finished, so it's judged by when
    it arrived here instead: its status change (Linux, macOS) or creation
    (Windows) time.
    """
    status = path.stat()
    if status.st_mtime <= now + CLOCK_SLACK_SECONDS:
        return status.st_mtime
    return min(status.st_ctime, now)


def move_aside(path: Path, folder_name: str, now: datetime | None = None) -> Path:
    """Move ``path`` into the folder ``folder_name`` beside it; where it went.

    A name already there gets the date and time added, so nothing is replaced.

    Raises:
        OSError: The file couldn't be moved.
    """
    into = path.parent / folder_name
    into.mkdir(exist_ok=True)
    target = into / path.name
    if target.exists():
        stamp = f"{(now or datetime.now()).astimezone():%Y-%m-%d %H.%M.%S}"  # noqa: DTZ005 (local time, for people)
        target = into / f"{path.stem} {stamp}{path.suffix}"
        number = 2
        while target.exists():
            target = into / f"{path.stem} {stamp} ({number}){path.suffix}"
            number += 1
    return Path(shutil.move(path, target))


def check_folder(
    connection: sqlite3.Connection,
    settings: ScannerSettings,
    *,
    now: float | None = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> FolderCheck:
    """Take the scanner folder's finished files in as sheets, reading them if chosen.

    ``should_stop`` is asked between files and sheets: the app is closing.
    """
    result = FolderCheck()
    folder = Path(settings.folder)
    try:
        ready, result.still_saving = files_to_take(folder, now)
    except OSError:
        result.problems.append(
            tr(
                "Couldn't open the scanner folder {folder}; it will be tried "
                "again at the next check."
            ).format(folder=folder)
        )
        return result
    with TemporaryDirectory(prefix="omr-scanner-", ignore_cleanup_errors=True) as pages:
        for path in ready:
            if should_stop():
                break
            _take(connection, path, Path(pages), result)
    if settings.read_automatically and result.added:
        _read(connection, result, should_stop)
    return result


def _take(
    connection: sqlite3.Connection, path: Path, pages: Path, result: FolderCheck
) -> None:
    """Add one file's sheets, then move it to Added, or to Couldn't add."""
    try:
        if not is_pdf(path) and not cv2.haveImageReader(str(path)):
            raise PdfError(path.name)  # noqa: TRY301 (handled as a PDF that can't open)
        images = images_to_add(path, pages)
        added = []
        for image, name in images:
            try:
                added.append(add_capture(connection, image, name))
            except DuplicateCaptureError:
                result.duplicates.append(name)
    except (PdfError, OSError):
        result.failed.append(path.name)
        destination = failed_folder_name()
    else:
        result.added.extend(added)
        destination = added_folder_name()
    try:
        move_aside(path, destination)
    except OSError:
        # Taken again at the next check: its sheets are then already added.
        result.problems.append(
            tr(
                "Couldn't move {file} into the scanner folder's \"{folder}\" folder."
            ).format(file=path.name, folder=destination)
        )


def _read(
    connection: sqlite3.Connection,
    result: FolderCheck,
    should_stop: Callable[[], bool],
) -> None:
    # Imported here: it loads the scanning engine, which mustn't hold up startup.
    from omr_data_collector.engine.reading import read_capture  # noqa: PLC0415

    paper_size = paper_size_of(load_organization(connection))
    for index, capture in enumerate(result.added):
        if should_stop():
            break
        done = read_capture(connection, capture, paper_size)
        result.added[index] = done
        if done.status == CAPTURE_STATUSES.READ:
            result.read += 1
        else:
            result.unreadable += 1


def check_summary(result: FolderCheck, *, asked: bool) -> str:
    """What a check did, in words for the status bar; "" if nothing worth saying.

    A check someone ``asked`` for always says something; a timed check that
    found nothing says nothing.
    """
    parts: list[str] = []
    if result.added:
        parts.append(
            tr("Added %n sheet(s) from the scanner folder.", None, len(result.added))
        )
        if result.read:
            parts.append(tr("Read %n of them.", None, result.read))
        if result.unreadable:
            parts.append(
                tr(
                    "%n couldn't be read; choose one to see why.",
                    None,
                    result.unreadable,
                )
            )
    if result.duplicates:
        parts.append(
            tr("Already added, so skipped: {files}.").format(
                files=", ".join(result.duplicates)
            )
        )
    if result.failed:
        parts.append(
            tr(
                "Couldn't add {files}: moved to the scanner folder's \"{folder}\" "
                "folder."
            ).format(files=", ".join(result.failed), folder=failed_folder_name())
        )
    parts.extend(result.problems)
    if result.still_saving and (asked or parts):
        parts.append(
            tr(
                "%n scan(s) may still be being saved; they will be added in a "
                "minute or so.",
                None,
                result.still_saving,
            )
        )
    if not parts and asked:
        parts.append(tr("No new scans in the scanner folder."))
    return " ".join(parts)
