from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from omr_data_collector.constants import (
    ANSWER_TYPES,
    MAX_SHEET_DETAIL_FIELDS,
    SHEET_DETAILS_PLACEMENTS,
    TABLE_NAME_MAX_LENGTH,
    WRITTEN_DATA_TYPES,
)
from omr_data_collector.i18n import tr
from omr_data_collector.models.AnswerSpec import AnswerSpec
from omr_data_collector.models.TableBlock import (
    Column,
    columns_from_list,
    columns_to_list,
)


def starter_fields() -> tuple[Column, ...]:
    """A common set to start from: when the sheet was filled in, and by whom."""

    def written(name: str, characters: int) -> Column:
        return Column(
            name, answer=AnswerSpec(ANSWER_TYPES.WRITTEN, max_characters=characters)
        )

    return (
        Column(
            tr("Date"),
            answer=AnswerSpec(
                ANSWER_TYPES.WRITTEN,
                data_type=WRITTEN_DATA_TYPES.DATE_TIME,
                date_time_format="YYYY/MM/DD",
            ),
        ),
        written(tr("Shift"), 6),
        written(tr("Manager"), 10),
        written(tr("Supervisor"), 10),
        written(tr("Staff"), 14),
    )


@dataclass(frozen=True)
class SheetDetails:
    """Details about a sheet and how it was filled in: date, shift, who filled it in.

    Each field is a label and its answer, like "Date: [boxes]" or "Shift: o Day
    o Night". In the header (the default) the fields are stacked beside the QR
    code on every page; along a line they run left to right where the block is,
    wrapping onto further lines. A field is
    set up like a table column (a name and how it's answered), and each one is
    read and exported like a question. Written on the form itself, so every
    organization can have its own set.
    """

    name: str
    fields: tuple[Column, ...] = field(default_factory=starter_fields)
    placement: str = SHEET_DETAILS_PLACEMENTS.HEADER
    sheet_details_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def normalized(self) -> SheetDetails:
        return replace(
            self,
            name=self.name.strip(),
            fields=tuple(column.normalized() for column in self.fields),
        )

    def to_dict(self) -> dict[str, Any]:
        """The JSON form a form keeps as its own copy of the block."""
        return {
            "id": self.sheet_details_id,
            "name": self.name,
            "fields": columns_to_list(self.fields),
            "placement": self.placement,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SheetDetails:
        return cls(
            name=data["name"],
            fields=columns_from_list(data["fields"]),
            # Stored before there was a choice: they were along a line.
            placement=data.get("placement", SHEET_DETAILS_PLACEMENTS.LINE),
            sheet_details_id=data["id"],
        )

    def validation_errors(self, other_names: set[str]) -> dict[str, str]:  # noqa: ARG002 (written on a form, so never in a library)
        """Map each invalid field to a message for the person editing it."""
        errors: dict[str, str] = {}
        if not self.name:
            errors["name"] = tr("Enter a name for the sheet details.")
        elif len(self.name) > TABLE_NAME_MAX_LENGTH:
            errors["name"] = tr(
                "Keep the name to %n character(s) or fewer.",
                None,
                TABLE_NAME_MAX_LENGTH,
            )
        if self.placement not in SHEET_DETAILS_PLACEMENTS.values():
            errors["placement"] = tr("Choose where the details go.")
        if not self.fields:
            errors["fields"] = tr("Add at least one field.")
        elif len(self.fields) > MAX_SHEET_DETAIL_FIELDS:
            errors["fields"] = tr(
                "Use at most %n field(s).", None, MAX_SHEET_DETAIL_FIELDS
            )
        seen: set[str] = set()
        for number, column in enumerate(self.fields, start=1):
            field_errors = column.validation_errors(set())
            if column.name.casefold() in seen and "name" not in field_errors:
                # Each field becomes an export column, so the names must differ.
                field_errors["name"] = tr(
                    'These sheet details already have a field called "{name}".'
                ).format(name=column.name)
            seen.add(column.name.casefold())
            if field_errors:
                first = next(iter(field_errors.values()))
                errors["fields"] = tr('Field {number} ("{name}"): {problem}').format(
                    number=number, name=column.name, problem=first
                )
                break
        return errors
