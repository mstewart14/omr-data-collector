from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Any

import jsonschema

from omr_data_collector.constants import (
    BLOCK_KINDS,
    FORM_NAME_MAX_LENGTH,
    PAGE_ORIENTATIONS,
    TABLE_BREAKS,
)
from omr_data_collector.models.Question import Question
from omr_data_collector.models.TableBlock import TableBlock
from omr_data_collector.models.TextBlock import TextBlock
from omr_data_collector.schemas.form_schema import FORM_DEFINITION_SCHEMA

BlockContent = TextBlock | Question | TableBlock

CONTENT_TYPES: dict[str, type[TextBlock | Question | TableBlock]] = {
    BLOCK_KINDS.TEXT: TextBlock,
    BLOCK_KINDS.QUESTION: Question,
    BLOCK_KINDS.TABLE: TableBlock,
}
KIND_NAMES = {
    BLOCK_KINDS.TEXT: "text",
    BLOCK_KINDS.QUESTION: "question",
    BLOCK_KINDS.TABLE: "table",
}


def content_id(content: BlockContent) -> str:
    """The ID of a library block, whichever kind it is."""
    if isinstance(content, TextBlock):
        return content.text_block_id
    if isinstance(content, Question):
        return content.question_id
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
            errors["name"] = "Enter a name for the form."
        elif len(self.name) > FORM_NAME_MAX_LENGTH:
            errors["name"] = (
                f"Keep the name to {FORM_NAME_MAX_LENGTH} characters or fewer."
            )
        elif self.name.casefold() in {name.casefold() for name in other_names}:
            errors["name"] = f'Another form is already called "{self.name}".'

        if self.orientation not in PAGE_ORIENTATIONS.values():
            errors["orientation"] = "Choose an orientation."

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
            return "Add at least one block."
        for number, block in enumerate(self.blocks, start=1):
            # A form's blocks are checked on their own: their names only need to
            # be unique within the form, which is checked below.
            content_errors = block.content.validation_errors(set())
            if content_errors:
                first = next(iter(content_errors.values()))
                return f'Block {number} ({KIND_NAMES[block.kind]} "{block.content.name}"): {first}'
        # Question and table names become export column and file names, so two
        # blocks of the same kind can't share one.
        for kind in (BLOCK_KINDS.QUESTION, BLOCK_KINDS.TABLE):
            seen: dict[str, int] = {}
            for number, block in enumerate(self.blocks, start=1):
                if block.kind != kind:
                    continue
                key = block.content.name.casefold()
                if key in seen:
                    return (
                        f"Blocks {seen[key]} and {number} are both "
                        f'{KIND_NAMES[kind]}s called "{block.content.name}"; '
                        "rename one so their data can be told apart."
                    )
                seen[key] = number
        return ""
