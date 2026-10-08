from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from omr_data_collector.constants import ANSWER_TYPES, QUESTION_NAME_MAX_LENGTH
from omr_data_collector.models.AnswerSpec import AnswerSpec


@dataclass(frozen=True)
class Question:
    """A reusable question and how its answer is collected (wiki 40001-40010).

    ``name`` identifies the question in the library and becomes its column name
    when data is exported; ``prompt`` is what's printed for the person answering,
    as Markdown like a text block's content; ``example`` is optional plain-text
    help printed with it.
    """

    name: str
    prompt: str = ""
    example: str = ""
    answer: AnswerSpec = field(
        default_factory=lambda: AnswerSpec.default(ANSWER_TYPES.YES_NO)
    )
    question_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        """The JSON form a form keeps as its own copy of the question."""
        return {
            "id": self.question_id,
            "name": self.name,
            "prompt": self.prompt,
            "example": self.example,
            "answer": self.answer.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Question:
        return cls(
            name=data["name"],
            prompt=data["prompt"],
            example=data["example"],
            answer=AnswerSpec.from_dict(data["answer"]),
            question_id=data["id"],
        )

    def normalized(self) -> Question:
        return replace(
            self,
            name=self.name.strip(),
            prompt=self.prompt.strip(),
            example=self.example.strip(),
            answer=self.answer.normalized(),
        )

    def validation_errors(self, other_names: set[str]) -> dict[str, str]:
        """Map each invalid field to a message for the person editing it.

        ``other_names`` are the names of every other saved question, compared
        ignoring case: they become export column names, which must not clash.
        """
        errors: dict[str, str] = {}
        if not self.name:
            errors["name"] = "Enter a name for the question."
        elif len(self.name) > QUESTION_NAME_MAX_LENGTH:
            errors["name"] = (
                f"Keep the name to {QUESTION_NAME_MAX_LENGTH} characters or fewer."
            )
        elif self.name.casefold() in {name.casefold() for name in other_names}:
            errors["name"] = f'Another question is already called "{self.name}".'

        if not self.prompt:
            errors["prompt"] = "Enter the question to print."

        errors.update(self.answer.validation_errors())
        return errors
