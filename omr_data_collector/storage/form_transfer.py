"""Moving a form between computers: one file with every version and its library blocks.

The form keeps its ID, so sheets printed on one computer can be read on the
other: a sheet's QR code names the form and version, and reading it needs that
version's definition and the page templates stored when it was printed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

import jsonschema

from omr_data_collector.constants import BLOCK_KINDS
from omr_data_collector.i18n import tr
from omr_data_collector.layout.omr_template import PageTemplate
from omr_data_collector.models.Form import CONTENT_TYPES, Form, content_id, kind_of
from omr_data_collector.models.naming import imported_name
from omr_data_collector.schemas.printed_layout_schema import PRINTED_LAYOUT_SCHEMA
from omr_data_collector.storage.question_store import list_questions, save_question
from omr_data_collector.storage.table_block_store import (
    list_table_blocks,
    save_table_block,
)
from omr_data_collector.storage.text_block_store import (
    list_text_blocks,
    save_text_block,
)

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable
    from pathlib import Path

    from omr_data_collector.models.Form import BlockContent

FILE_FORMAT = "omr-data-collector-form"
FILE_FORMAT_VERSION = 1
FILE_SUFFIX = ".omrform"
# Real exports are tens of kilobytes; a form with hundreds of printed versions
# stays well under this. A larger file is read no further.
MAX_FILE_BYTES = 20 * 1024 * 1024

# The library kinds a form's blocks can be copied from (sheet details have none).
LIBRARY_KINDS = (BLOCK_KINDS.TEXT, BLOCK_KINDS.QUESTION, BLOCK_KINDS.TABLE)

_ID = re.compile(r"^[0-9a-f]{32}$")


class FormFileError(Exception):
    """The file isn't a form exported by this app; the message says why."""


@dataclass(frozen=True)
class StoredVersion:
    """One row of ``form_version``, as it travels in the file."""

    version: int
    definition: dict[str, Any]
    printed_at: str | None = None
    printed_layout: dict[str, Any] | None = None

    @property
    def printed(self) -> bool:
        return self.printed_at is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "definition": self.definition,
            "printedAt": self.printed_at,
            "printedLayout": self.printed_layout,
        }


@dataclass(frozen=True)
class FormFile:
    """A form as exported: its ID, every version, and the library blocks it uses."""

    form_id: str
    versions: tuple[StoredVersion, ...]
    library: tuple[BlockContent, ...] = ()

    @property
    def name(self) -> str:
        return self.versions[-1].definition["name"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FILE_FORMAT,
            "formatVersion": FILE_FORMAT_VERSION,
            "formId": self.form_id,
            "versions": [version.to_dict() for version in self.versions],
            "library": [
                {"kind": kind_of(block), "content": block.to_dict()}
                for block in self.library
            ],
        }


# --- Export ---------------------------------------------------------------------


def stored_versions(
    connection: sqlite3.Connection, form_id: str
) -> tuple[StoredVersion, ...]:
    """Every stored version of a form, oldest first."""
    rows = connection.execute(
        "SELECT version, definition, printed_at, printed_layout FROM form_version"
        " WHERE form_id = ? ORDER BY version",
        (form_id,),
    ).fetchall()
    return tuple(
        StoredVersion(
            version=row["version"],
            definition=json.loads(row["definition"]),
            printed_at=row["printed_at"],
            printed_layout=(
                json.loads(row["printed_layout"]) if row["printed_layout"] else None
            ),
        )
        for row in rows
    )


def _library(connection: sqlite3.Connection) -> list[BlockContent]:
    return [
        *list_text_blocks(connection),
        *list_questions(connection),
        *list_table_blocks(connection),
    ]


def library_blocks_used(
    connection: sqlite3.Connection, form_id: str
) -> list[BlockContent]:
    """The library blocks any version of the form was copied from, still in the library."""
    sources = {
        block["sourceId"]
        for version in stored_versions(connection, form_id)
        for block in version.definition["blocks"]
        if block["sourceId"] is not None
    }
    return [block for block in _library(connection) if content_id(block) in sources]


def form_file(
    connection: sqlite3.Connection, form_id: str, *, with_library: bool = True
) -> FormFile:
    """The stored form, ready to write, with the library blocks it uses if asked.

    The form doesn't need them: every version holds its own copy of each block,
    which is all printing and reading sheets use. They're for editing the
    library on the other computer.
    """
    versions = stored_versions(connection, form_id)
    library = tuple(library_blocks_used(connection, form_id)) if with_library else ()
    return FormFile(form_id=form_id, versions=versions, library=library)


def write_form_file(path: Path, exported: FormFile) -> None:
    """Write the form to ``path``.

    Raises:
        OSError: The file couldn't be written.
    """
    path.write_text(
        json.dumps(exported.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
    )


# --- Reading a file ---------------------------------------------------------------


def read_form_file(path: Path) -> FormFile:
    """Read and check an exported form; nothing is stored.

    Raises:
        FormFileError: The file can't be read, or isn't an exported form.
    """
    try:
        too_large = path.stat().st_size > MAX_FILE_BYTES
        data = None if too_large else json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FormFileError(
            tr("The file couldn't be read as an exported form: {problem}").format(
                problem=error
            )
        ) from error
    if too_large:
        raise FormFileError(tr("The file is too large to be an exported form."))
    if not isinstance(data, dict) or data.get("format") != FILE_FORMAT:
        raise FormFileError(tr("The file isn't a form exported by this app."))
    if data.get("formatVersion") != FILE_FORMAT_VERSION:
        raise FormFileError(
            tr(
                "The form was exported by a newer version of the app; update this "
                "one to import it."
            )
        )
    try:
        return _parse(data)
    except (
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        jsonschema.ValidationError,
    ) as error:
        raise FormFileError(
            tr("The file is damaged or incomplete, so the form can't be imported.")
        ) from error


def _parse(data: dict[str, Any]) -> FormFile:
    form_id = data["formId"]
    if not isinstance(form_id, str) or not _ID.match(form_id):
        raise ValueError(form_id)
    versions = [_parse_version(entry, form_id) for entry in data["versions"]]
    numbers = [version.version for version in versions]
    if not versions or numbers != sorted(set(numbers)):
        raise ValueError(numbers)
    if any(not version.printed for version in versions[:-1]):
        # Only the latest version can be unprinted, as in the app's own database.
        raise ValueError(numbers)
    library = tuple(_parse_library_block(entry) for entry in data["library"])
    return FormFile(form_id=form_id, versions=tuple(versions), library=library)


def _parse_version(entry: dict[str, Any], form_id: str) -> StoredVersion:
    version = entry["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError(version)
    # Each definition is checked as the app checks its own stored ones.
    Form.from_definition(entry["definition"], form_id=form_id, version=version)
    printed_at = entry["printedAt"]
    layout = entry["printedLayout"]
    if printed_at is not None and not isinstance(printed_at, str):
        raise TypeError(printed_at)
    if layout is not None:
        jsonschema.validate(instance=layout, schema=PRINTED_LAYOUT_SCHEMA)
        for page in layout["pages"]:
            PageTemplate.from_dict(page)
    return StoredVersion(version, entry["definition"], printed_at, layout)


def _parse_library_block(entry: dict[str, Any]) -> BlockContent:
    kind = entry["kind"]
    if kind not in LIBRARY_KINDS:
        raise ValueError(kind)
    block = CONTENT_TYPES[kind].from_dict(entry["content"]).normalized()
    if not _ID.match(content_id(block)) or block.validation_errors(set()):
        raise ValueError(content_id(block))
    return block


# --- Importing ----------------------------------------------------------------------


@dataclass(frozen=True)
class ImportPlan:
    """What importing a file would do, worked out before anything is stored.

    ``problem`` says why it can't be imported at all. ``choose_latest`` is set
    when this computer and the file each have changes the other lacks, and only
    one can be the form's latest version: the person picks. ``changed_blocks``
    are library blocks here that differ from the file's: the person picks
    whether to replace them.
    """

    exported: FormFile
    problem: str = ""
    choose_latest: bool = False
    new_form: bool = False
    changed_blocks: tuple[BlockContent, ...] = ()
    local: tuple[StoredVersion, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class ImportResult:
    form_id: str
    name: str
    added_versions: tuple[int, ...] = ()
    took_file_changes: bool = False
    added_blocks: int = 0
    replaced_blocks: int = 0
    # Library blocks added under a new name, since this computer has another
    # block by that name: (name in the file, name here).
    renamed_blocks: tuple[tuple[str, str], ...] = ()

    @property
    def changed_anything(self) -> bool:
        return bool(
            self.added_versions
            or self.took_file_changes
            or self.added_blocks
            or self.replaced_blocks
        )


def _draft(versions: tuple[StoredVersion, ...]) -> StoredVersion | None:
    """The unprinted latest version, if any, unless it's the same as one printed."""
    if not versions or versions[-1].printed:
        return None
    draft = versions[-1]
    if any(version.definition == draft.definition for version in versions[:-1]):
        return None
    return draft


def _behind(draft: StoredVersion | None, other: tuple[StoredVersion, ...]) -> bool:
    """Whether the other side printed a version at or past this draft's number."""
    return draft is not None and any(
        version.printed and version.version >= draft.version for version in other
    )


def plan_import(connection: sqlite3.Connection, exported: FormFile) -> ImportPlan:
    """Compare the file with what's stored here, without changing anything."""
    local = stored_versions(connection, exported.form_id)
    plan = ImportPlan(
        exported=exported,
        new_form=not local,
        local=local,
        changed_blocks=_changed_blocks(connection, exported.library),
    )
    local_printed = {version.version: version for version in local if version.printed}
    for version in exported.versions:
        mine = local_printed.get(version.version)
        if (
            version.printed
            and mine is not None
            and mine.definition != version.definition
        ):
            return replace(
                plan,
                problem=tr(
                    "Version {version} of this form was printed on both computers, "
                    "with different contents, so sheets printed from it couldn't be "
                    "told apart. It can't be imported."
                ).format(version=version.version),
            )

    local_draft = _draft(local)
    file_draft = _draft(exported.versions)
    choose = (
        (
            local_draft is not None
            and file_draft is not None
            and local_draft.definition != file_draft.definition
        )
        or _behind(local_draft, exported.versions)
        or _behind(file_draft, local)
    )
    plan = replace(plan, choose_latest=choose)

    name = _merged(plan, keep_local=True)[-1].definition["name"]
    if choose:
        # Either could become the name; both must be free.
        names = {name, _merged(plan, keep_local=False)[-1].definition["name"]}
    else:
        names = {name}
    taken = connection.execute(
        "SELECT name FROM form WHERE form_id != ?", (exported.form_id,)
    ).fetchall()
    for row in taken:
        if row["name"].casefold() in {other.casefold() for other in names}:
            return replace(
                plan,
                problem=tr(
                    'Another form here is already called "{name}". Rename it, then '
                    "import again."
                ).format(name=row["name"]),
            )
    return plan


def _chosen_draft(plan: ImportPlan, *, keep_local: bool) -> StoredVersion | None:
    """Whose unprinted changes become the latest version, if anyone's.

    ``keep_local`` picks when ``choose_latest``.
    """
    local_draft = _draft(plan.local)
    file_draft = _draft(plan.exported.versions)
    if plan.choose_latest:
        return local_draft if keep_local else file_draft
    return local_draft or file_draft


def _merged(plan: ImportPlan, *, keep_local: bool) -> list[StoredVersion]:
    """Every version the form will have: all printed ones, then the latest changes."""
    printed: dict[int, StoredVersion] = {}
    for version in (*plan.exported.versions, *plan.local):
        if version.printed:
            printed.setdefault(version.version, version)
    merged = [printed[number] for number in sorted(printed)]
    draft = _chosen_draft(plan, keep_local=keep_local)
    if draft is not None:
        top = merged[-1].version if merged else 0
        merged.append(replace(draft, version=top + 1))
    return merged


def apply_import(
    connection: sqlite3.Connection,
    plan: ImportPlan,
    *,
    keep_local: bool = True,
    add_blocks: bool = True,
    replace_blocks: bool = False,
) -> ImportResult:
    """Store the imported form and, if ``add_blocks``, the file's library blocks.

    ``keep_local`` answers ``plan.choose_latest``; ``replace_blocks`` whether
    the file's copies of ``plan.changed_blocks`` replace this computer's.
    The form is stored in one transaction, then the library blocks, each of
    which the library stores save in its own.
    """
    if plan.problem:
        raise ValueError(plan.problem)
    exported = plan.exported
    merged = _merged(plan, keep_local=keep_local)
    # Printed here already; any unprinted version here is replaced below.
    printed_here = {version.version for version in plan.local if version.printed}
    added = tuple(
        version.version
        for version in merged
        if version.printed and version.version not in printed_here
    )
    local_draft = _draft(plan.local)
    chosen = _chosen_draft(plan, keep_local=keep_local)
    took_file_changes = chosen is not None and (
        local_draft is None or chosen.definition != local_draft.definition
    )
    name = merged[-1].definition["name"]
    if [version.to_dict() for version in merged] != [
        version.to_dict() for version in plan.local
    ]:
        with connection:
            connection.execute(
                "INSERT INTO form (form_id, name) VALUES (?, ?)"
                " ON CONFLICT(form_id) DO UPDATE SET name = excluded.name,"
                " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                (exported.form_id, name),
            )
            # Printed versions never change; only the unprinted one is replaced.
            connection.execute(
                "DELETE FROM form_version WHERE form_id = ? AND printed_at IS NULL",
                (exported.form_id,),
            )
            for version in merged:
                if version.version in printed_here:
                    continue
                connection.execute(
                    "INSERT INTO form_version (form_id, version, definition,"
                    " printed_at, printed_layout) VALUES (?, ?, ?, ?, ?)",
                    (
                        exported.form_id,
                        version.version,
                        json.dumps(version.definition),
                        version.printed_at,
                        json.dumps(version.printed_layout)
                        if version.printed_layout is not None
                        else None,
                    ),
                )
    added_blocks, replaced, renamed = (
        _import_library(connection, exported.library, replace_blocks=replace_blocks)
        if add_blocks
        else (0, 0, ())
    )
    return ImportResult(
        form_id=exported.form_id,
        name=name,
        added_versions=added,
        took_file_changes=took_file_changes,
        added_blocks=added_blocks,
        replaced_blocks=replaced,
        renamed_blocks=renamed,
    )


def _changed_blocks(
    connection: sqlite3.Connection, library: tuple[BlockContent, ...]
) -> tuple[BlockContent, ...]:
    """This computer's library blocks that the file has different copies of."""
    here = {content_id(block): block for block in _library(connection)}
    return tuple(
        here[content_id(block)]
        for block in library
        if content_id(block) in here and here[content_id(block)] != block
    )


_SAVERS: dict[str, Callable[[sqlite3.Connection, Any], None]] = {
    BLOCK_KINDS.TEXT: save_text_block,
    BLOCK_KINDS.QUESTION: save_question,
    BLOCK_KINDS.TABLE: save_table_block,
}


def _import_library(
    connection: sqlite3.Connection,
    library: tuple[BlockContent, ...],
    *,
    replace_blocks: bool,
) -> tuple[int, int, tuple[tuple[str, str], ...]]:
    """Add the file's library blocks; returns counts added and replaced, and renames."""
    here = {content_id(block): block for block in _library(connection)}
    added = 0
    replaced = 0
    renamed: list[tuple[str, str]] = []
    for block in library:
        kind = kind_of(block)
        mine = here.get(content_id(block))
        if mine is not None:
            if mine == block or not replace_blocks:
                continue
            replaced += 1
        else:
            added += 1
        names = {
            other.name
            for other in _library(connection)
            if kind_of(other) == kind and content_id(other) != content_id(block)
        }
        if block.name.casefold() in {name.casefold() for name in names}:
            new_name = imported_name(block.name, names)
            renamed.append((block.name, new_name))
            block = replace(block, name=new_name)  # noqa: PLW2901 (stored renamed)
        _SAVERS[kind](connection, block)
    return added, replaced, tuple(renamed)
