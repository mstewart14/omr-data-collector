from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Any

import jsonschema

from omr_data_collector.constants import (
    BLOCK_KINDS,
    FORM_NAME_MAX_LENGTH,
    PAGE_ORIENTATIONS,
    SHEET_DETAILS_PLACEMENTS,
    TABLE_BREAKS,
)
from omr_data_collector.i18n import tr
from omr_data_collector.models.Question import Question
from omr_data_collector.models.SheetDetails import SheetDetails
from omr_data_collector.models.TableBlock import TableBlock
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.schemas.form_schema import FORM_DEFINITION_SCHEMA

BlockContent = TextBlock | Question | TableBlock | SheetDetails

CONTENT_TYPES: dict[str, type[BlockContent]] = {
    BLOCK_KINDS.TEXT: TextBlock,
    BLOCK_KINDS.QUESTION: Question,
    BLOCK_KINDS.TABLE: TableBlock,
    BLOCK_KINDS.SHEET_DETAILS: SheetDetails,
}


def kind_name(kind: str) -> str:
    """What a block of ``kind`` is called, as a noun inside a sentence."""
    return {
        BLOCK_KINDS.TEXT: tr("text block"),
        BLOCK_KINDS.QUESTION: tr("question"),
        BLOCK_KINDS.TABLE: tr("table"),
        BLOCK_KINDS.SHEET_DETAILS: tr("sheet details"),
    }[kind]


def kind_title(kind: str) -> str:
    """What a block of ``kind`` is called, on its own (a heading or list entry)."""
    return {
        BLOCK_KINDS.TEXT: tr("Text block"),
        BLOCK_KINDS.QUESTION: tr("Question"),
        BLOCK_KINDS.TABLE: tr("Table"),
        BLOCK_KINDS.SHEET_DETAILS: tr("Sheet details"),
    }[kind]


def content_id(content: BlockContent) -> str:
    """The ID of a library block, whichever kind it is."""
    if isinstance(content, TextBlock):
        return content.text_block_id
    if isinstance(content, Question):
        return content.question_id
    if isinstance(content, SheetDetails):
        return content.sheet_details_id
    return content.table_block_id


def kind_of(content: BlockContent) -> str:
    return next(
        kind
        for kind, kind_type in CONTENT_TYPES.items()
        if isinstance(content, kind_type)
    )


@dataclass(frozen=True)
class FormBlock:
    """One block stacked on a form: the form's own copy of a text, question or table.

    ``source_id`` is the library block it was copied from (wiki 50011), or None for
    one written on the form itself (50002, 50004). The copy never changes when the
    library block does, unless the person chooses "everywhere" there (50012).
    """

    content: BlockContent
    source_id: str | None = None
    # Begin a new page with this block, even if it would fit (50005).
    start_on_new_page: bool = False
    # For tables: split across pages, or move to a new page, when it doesn't fit.
    table_break: str = TABLE_BREAKS.SPLIT
    block_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def kind(self) -> str:
        return kind_of(self.content)

    def normalized(self) -> FormBlock:
        return replace(self, content=self.content.normalized())

    def to_dict(self) -> dict[str, Any]:
        return {
            "blockId": self.block_id,
            "kind": self.kind,
            "sourceId": self.source_id,
            "startOnNewPage": self.start_on_new_page,
            "tableBreak": self.table_break,
            "content": self.content.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FormBlock:
        return cls(
            content=CONTENT_TYPES[data["kind"]].from_dict(data["content"]),
            source_id=data["sourceId"],
            start_on_new_page=data["startOnNewPage"],
            table_break=data["tableBreak"],
            block_id=data["blockId"],
        )


@dataclass(frozen=True)
class Form:
    """A paper form: blocks stacked down its pages (wiki 50001-50012).

    Every page has a header with the organization's identity and, always in the
    top-right corner, a QR code naming the form and its version. ``version`` is
    the stored version this was loaded from; 0 for a form never saved.
    """

    name: str
    orientation: str = PAGE_ORIENTATIONS.PORTRAIT
    blocks: tuple[FormBlock, ...] = ()
    form_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    version: int = 0

    def normalized(self) -> Form:
        return replace(
            self,
            name=self.name.strip(),
            blocks=tuple(block.normalized() for block in self.blocks),
        )

    def validation_errors(self, other_names: set[str]) -> dict[str, str]:
        """Map each invalid field to a message for the person editing it.

        ``other_names`` are the names of every other saved form, compared ignoring
        case.
        """
        errors: dict[str, str] = {}
        if not self.name:
            errors["name"] = tr("Enter a name for the form.")
        elif len(self.name) > FORM_NAME_MAX_LENGTH:
            errors["name"] = tr(
                "Keep the name to %n character(s) or fewer.", None, FORM_NAME_MAX_LENGTH
            )
        elif self.name.casefold() in {name.casefold() for name in other_names}:
            errors["name"] = tr('Another form is already called "{name}".').format(
                name=self.name
            )

        if self.orientation not in PAGE_ORIENTATIONS.values():
            errors["orientation"] = tr("Choose an orientation.")

        blocks_error = self._blocks_error()
        if blocks_error:
            errors["blocks"] = blocks_error
        return errors

    def definition(self) -> dict[str, Any]:
        """The JSON stored for each version: everything needed to print or scan it."""
        return {
            "name": self.name,
            "orientation": self.orientation,
            "blocks": [block.to_dict() for block in self.blocks],
        }

    @classmethod
    def from_definition(
        cls, data: dict[str, Any], *, form_id: str, version: int
    ) -> Form:
        """Read a stored version back.

        Raises:
            jsonschema.ValidationError: ``data`` isn't a stored form definition.
        """
        jsonschema.validate(instance=data, schema=FORM_DEFINITION_SCHEMA)
        return cls(
            name=data["name"],
            orientation=data["orientation"],
            blocks=tuple(FormBlock.from_dict(block) for block in data["blocks"]),
            form_id=form_id,
            version=version,
        )

    def _blocks_error(self) -> str:
        if not self.blocks:
            return tr("Add at least one block.")
        for number, block in enumerate(self.blocks, start=1):
            # A form's blocks are checked on their own: their names only need to
            # be unique within the form, which is checked below.
            content_errors = block.content.validation_errors(set())
            if content_errors:
                first = next(iter(content_errors.values()))
                return tr('Block {number} ({kind} "{name}"): {problem}').format(
                    number=number,
                    kind=kind_name(block.kind),
                    name=block.content.name,
                    problem=first,
                )
        details_error = self._sheet_details_error()
        if details_error:
            return details_error
        # Question and table names become export column and file names, so two
        # blocks of the same kind can't share one.
        for kind in (BLOCK_KINDS.QUESTION, BLOCK_KINDS.TABLE):
            seen: dict[str, int] = {}
            for number, block in enumerate(self.blocks, start=1):
                if block.kind != kind:
                    continue
                key = block.content.name.casefold()
                if key in seen:
                    message = (
                        tr(
                            "Blocks {first} and {second} are both questions called "
                            '"{name}"; rename one so their data can be told apart.'
                        )
                        if kind == BLOCK_KINDS.QUESTION
                        else tr(
                            "Blocks {first} and {second} are both tables called "
                            '"{name}"; rename one so their data can be told apart.'
                        )
                    )
                    return message.format(
                        first=seen[key], second=number, name=block.content.name
                    )
                seen[key] = number
        return ""

    def _sheet_details_error(self) -> str:
        """One header set of sheet details at most, and no field named as a question."""
        in_header = [
            number
            for number, block in enumerate(self.blocks, start=1)
            if isinstance(block.content, SheetDetails)
            and block.content.placement == SHEET_DETAILS_PLACEMENTS.HEADER
        ]
        if len(in_header) > 1:
            return tr(
                "Blocks {first} and {second} are both sheet details in the header, "
                "which has room for one; put one along a line instead."
            ).format(first=in_header[0], second=in_header[1])
        # Sheet details and questions are columns of the same exported file.
        detail_names = {
            column.name.casefold(): column.name
            for block in self.blocks
            if isinstance(block.content, SheetDetails)
            for column in block.content.fields
        }
        for block in self.blocks:
            if (
                isinstance(block.content, Question)
                and block.content.name.casefold() in detail_names
            ):
                return tr(
                    'The question "{name}" has the same name as a sheet details '
                    "field; rename one so their data can be told apart."
                ).format(name=block.content.name)
        return ""
