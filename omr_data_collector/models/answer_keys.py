"""A form's answers by name, to match them across the form's versions.

Each version of a form numbers its blocks afresh, so an answer on a sheet from
one version is found in another by what it's exported as: its kind and names
(``AnswerKey``). Export translates older sheets' bubbles this way, and both the
Capture screen and export use it to leave out answers that the latest version
says aren't entered (wiki 60016), on sheets printed from any version.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omr_data_collector.models.Question import Question
from omr_data_collector.models.SheetDetails import SheetDetails
from omr_data_collector.models.TableBlock import TableBlock

if TYPE_CHECKING:
    from omr_data_collector.models.AnswerSpec import AnswerSpec
    from omr_data_collector.models.Capture import CapturedAnswer
    from omr_data_collector.models.Form import Form

# ("details", None, field), ("question", None, question) or
# ("table", table, column).
AnswerKey = tuple[str, str | None, str]


def answer_specs(form: Form) -> dict[AnswerKey, AnswerSpec]:
    """Each of ``form``'s answers by what it's exported as: its kind and names."""
    specs: dict[AnswerKey, AnswerSpec] = {}
    for block in form.blocks:
        content = block.content
        if isinstance(content, SheetDetails):
            for column in content.fields:
                specs["details", None, column.name] = column.answer
        elif isinstance(content, Question):
            specs["question", None, content.name] = content.answer
        elif isinstance(content, TableBlock):
            for column in content.columns:
                specs["table", content.name, column.name] = column.answer
    return specs


def answer_key(form: Form, answer: CapturedAnswer) -> AnswerKey | None:
    """The key of a captured answer on a sheet from ``form``; None if not found."""
    if not 0 <= answer.block_index < len(form.blocks):
        return None
    content = form.blocks[answer.block_index].content
    if isinstance(content, Question):
        return "question", None, content.name
    column = -1 if answer.column is None else answer.column
    if isinstance(content, SheetDetails) and 0 <= column < len(content.fields):
        return "details", None, content.fields[column].name
    if isinstance(content, TableBlock) and 0 <= column < len(content.columns):
        return "table", content.name, content.columns[column].name
    return None


def not_entered(versions: list[Form]) -> set[AnswerKey]:
    """The answers not entered, given a form's ``versions``, latest first.

    The latest version having an answer decides: setting an answer as not
    entered doesn't change the paper, so sheets printed before it was set
    skip it too.
    """
    decided: dict[AnswerKey, bool] = {}
    for version in versions:
        for key, spec in answer_specs(version).items():
            decided.setdefault(key, spec.is_entered)
    return {key for key, entered in decided.items() if not entered}
