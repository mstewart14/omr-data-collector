from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Any

import jsonschema

from omr_data_collector.constants import (
    ANSWER_TYPES,
    COLUMN_NAME_MAX_LENGTH,
    DEFAULT_TABLE_ROWS,
    MAX_TABLE_ROWS,
    TABLE_NAME_MAX_LENGTH,
)
from omr_data_collector.models.AnswerSpec import AnswerSpec
from omr_data_collector.schemas.table_columns_schema import TABLE_COLUMNS_SCHEMA


@dataclass(frozen=True)
class Column:
    """One column of a table block: a heading, an example and how it's answered."""

    name: str
    example: str = ""
    answer: AnswerSpec = field(
        default_factory=lambda: AnswerSpec.default(ANSWER_TYPES.YES_NO)
    )

    def normalized(self) -> Column:
        return replace(
            self,
            name=self.name.strip(),
            example=self.example.strip(),
            answer=self.answer.normalized(),
        )

    def validation_errors(self, other_names: set[str]) -> dict[str, str]:
        """Map each invalid field to a message for the person editing it.

        ``other_names`` are the table's other column names, which must differ
        (ignoring case) since each becomes an export column.
        """
        errors: dict[str, str] = {}
        if not self.name:
            errors["name"] = "Enter a name for the column."
        elif len(self.name) > COLUMN_NAME_MAX_LENGTH:
            errors["name"] = (
                f"Keep the name to {COLUMN_NAME_MAX_LENGTH} characters or fewer."
            )
        elif self.name.casefold() in {name.casefold() for name in other_names}:
            errors["name"] = f'This table already has a column called "{self.name}".'
        errors.update(self.answer.validation_errors())
        return errors


@dataclass(frozen=True)
class TableBlock:
    """A reusable table: a row per person or visit, a column per thing recorded.

    Covers wiki stories 30001-30010. ``instructions`` is Markdown, like a text
    block's content. With ``fill_page`` the table gets as many rows as fit below
    where it is placed on its page, worked out when a form is laid out; ``rows``
    is kept for when it's turned off.
    """

    name: str
    instructions: str = ""
    rows: int = DEFAULT_TABLE_ROWS
    fill_page: bool = False
    columns: tuple[Column, ...] = ()
    table_block_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def normalized(self) -> TableBlock:
        return replace(
            self,
            name=self.name.strip(),
            columns=tuple(column.normalized() for column in self.columns),
        )

    def validation_errors(self, other_names: set[str]) -> dict[str, str]:
        """Map each invalid field to a message for the person editing it.

        ``other_names`` are the names of every other saved table, compared
        ignoring case.
        """
        errors: dict[str, str] = {}
        if not self.name:
            errors["name"] = "Enter a name for the table."
        elif len(self.name) > TABLE_NAME_MAX_LENGTH:
            errors["name"] = (
                f"Keep the name to {TABLE_NAME_MAX_LENGTH} characters or fewer."
            )
        elif self.name.casefold() in {name.casefold() for name in other_names}:
            errors["name"] = f'Another table is already called "{self.name}".'

        if not 1 <= self.rows <= MAX_TABLE_ROWS:
            errors["rows"] = f"Use between 1 and {MAX_TABLE_ROWS} rows."

        if not self.columns:
            errors["columns"] = "Add at least one column."
        for number, column in enumerate(self.columns, start=1):
            # By position, not identity: two identical columns are still two.
            others = {
                other.name
                for other_number, other in enumerate(self.columns, start=1)
                if other_number != number
            }
            column_errors = column.validation_errors(others)
            if column_errors:
                first = next(iter(column_errors.values()))
                errors["columns"] = (
                    f'Column {number} ("{column.name}"): {first}'
                    if column.name
                    else f"Column {number}: {first}"
                )
                break
        return errors


def columns_to_list(columns: tuple[Column, ...]) -> list[dict[str, Any]]:
    """The JSON form stored in the database and copied into forms."""
    return [
        {
            "name": column.name,
            "example": column.example,
            "answer": column.answer.to_dict(),
        }
        for column in columns
    ]


def columns_from_list(data: list[dict[str, Any]]) -> tuple[Column, ...]:
    """Read the JSON form back.

    Raises:
        jsonschema.ValidationError: ``data`` isn't a stored column list.
    """
    jsonschema.validate(instance=data, schema=TABLE_COLUMNS_SCHEMA)
    return tuple(
        Column(
            name=column["name"],
            example=column["example"],
            answer=AnswerSpec.from_dict(column["answer"]),
        )
        for column in data
    )
