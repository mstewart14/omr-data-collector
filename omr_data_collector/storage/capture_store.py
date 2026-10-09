"""Captured sheets: their images (copied beside the database) and their data."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from omr_data_collector.models.Capture import Capture, CapturedAnswer

if TYPE_CHECKING:
    import sqlite3

CAPTURES_DIR_NAME = "captures"
CAPTURE_COLUMNS = (
    "capture_id, file_name, original_name, content_hash, status, problem,"
    " form_id, form_version, page, answers, added_at"
)


class DuplicateCaptureError(Exception):
    """The image has been added already; ``existing`` is the capture it became."""

    def __init__(self, existing: Capture) -> None:
        super().__init__(existing.original_name)
        self.existing = existing


def captures_dir(connection: sqlite3.Connection) -> Path:
    """The folder of captured images: ``captures`` beside the database file."""
    row = connection.execute(
        "SELECT file FROM pragma_database_list WHERE name = 'main'"
    ).fetchone()
    return Path(row["file"]).parent / CAPTURES_DIR_NAME


def image_path(connection: sqlite3.Connection, capture: Capture) -> Path:
    return captures_dir(connection) / capture.file_name


def page_image_path(connection: sqlite3.Connection, capture: Capture) -> Path:
    """The page as straightened when it was read (it may not exist yet)."""
    return captures_dir(connection) / capture.page_image_name


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_capture(connection: sqlite3.Connection, source: Path) -> Capture:
    """Copy the image at ``source`` into the captures folder, waiting to be read.

    Raises:
        DuplicateCaptureError: The same image (byte for byte) was added before.
        OSError: The image couldn't be read or copied.
    """
    content_hash = file_hash(source)
    existing = connection.execute(
        f"SELECT {CAPTURE_COLUMNS} FROM capture WHERE content_hash = ?",  # noqa: S608 (fixed column list)
        (content_hash,),
    ).fetchone()
    if existing is not None:
        raise DuplicateCaptureError(_capture(existing))
    capture_id = uuid.uuid4().hex
    capture = Capture(
        capture_id=capture_id,
        file_name=f"{capture_id}{source.suffix.lower()}",
        original_name=source.name,
        content_hash=content_hash,
    )
    destination = image_path(connection, capture)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    with connection:
        connection.execute(
            "INSERT INTO capture (capture_id, file_name, original_name, content_hash,"
            " status) VALUES (?, ?, ?, ?, ?)",
            (
                capture.capture_id,
                capture.file_name,
                capture.original_name,
                capture.content_hash,
                capture.status,
            ),
        )
    return load_capture(connection, capture_id) or capture


def list_captures(connection: sqlite3.Connection) -> list[Capture]:
    """Every capture, in the order they were added."""
    rows = connection.execute(
        f"SELECT {CAPTURE_COLUMNS} FROM capture ORDER BY added_at, rowid"  # noqa: S608 (fixed column list)
    ).fetchall()
    return [_capture(row) for row in rows]


def load_capture(connection: sqlite3.Connection, capture_id: str) -> Capture | None:
    row = connection.execute(
        f"SELECT {CAPTURE_COLUMNS} FROM capture WHERE capture_id = ?",  # noqa: S608 (fixed column list)
        (capture_id,),
    ).fetchone()
    return _capture(row) if row is not None else None


def save_capture(connection: sqlite3.Connection, capture: Capture) -> None:
    """Store a capture's status, page and answers."""
    with connection:
        connection.execute(
            "UPDATE capture SET status = ?, problem = ?, form_id = ?,"
            " form_version = ?, page = ?, answers = ?,"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
            " WHERE capture_id = ?",
            (
                capture.status,
                capture.problem,
                capture.form_id,
                capture.form_version,
                capture.page,
                json.dumps([answer.to_dict() for answer in capture.answers]),
                capture.capture_id,
            ),
        )


def delete_capture(connection: sqlite3.Connection, capture: Capture) -> None:
    """Remove a capture and its images."""
    with connection:
        connection.execute(
            "DELETE FROM capture WHERE capture_id = ?", (capture.capture_id,)
        )
    for path in (image_path(connection, capture), page_image_path(connection, capture)):
        path.unlink(missing_ok=True)


def _capture(row: sqlite3.Row) -> Capture:
    return Capture(
        capture_id=row["capture_id"],
        file_name=row["file_name"],
        original_name=row["original_name"],
        content_hash=row["content_hash"],
        status=row["status"],
        problem=row["problem"],
        form_id=row["form_id"],
        form_version=row["form_version"],
        page=row["page"],
        answers=tuple(
            CapturedAnswer.from_dict(answer) for answer in json.loads(row["answers"])
        ),
        added_at=row["added_at"],
    )
