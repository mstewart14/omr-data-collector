from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace

from omr_data_collector.constants import TEXT_BLOCK_NAME_MAX_LENGTH


@dataclass(frozen=True)
class TextBlock:
    """Reusable formatted text for forms: titles, instructions, footers.

    Covers wiki stories 10001-10005. ``content`` is Markdown (CommonMark with
    GitHub's extensions, no raw HTML), which the editor and Qt's printing read and
    write directly.
    """

    name: str
    content: str = ""
    text_block_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def normalized(self) -> TextBlock:
        return replace(self, name=self.name.strip())

    def validation_errors(self, other_names: set[str]) -> dict[str, str]:
        """Map each invalid field to a message for the person editing it.

        ``other_names`` are the names of every other saved text block; names are
        compared ignoring case, since the form builder lists blocks by name.
        """
        errors: dict[str, str] = {}

        if not self.name:
            errors["name"] = "Enter a name for the text block."
        elif len(self.name) > TEXT_BLOCK_NAME_MAX_LENGTH:
            errors["name"] = (
                f"Keep the name to {TEXT_BLOCK_NAME_MAX_LENGTH} characters or fewer."
            )
        elif self.name.casefold() in {name.casefold() for name in other_names}:
            errors["name"] = f'Another text block is already called "{self.name}".'

        if not self.content.strip():
            errors["content"] = "Enter the text for the block."

        return errors
