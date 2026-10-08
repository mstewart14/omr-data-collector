from __future__ import annotations

import sqlite3

import pytest

from omr_data_collector.constants import ANSWER_TYPES, WRITTEN_DATA_TYPES
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice
from omr_data_collector.models.Question import Question
from omr_data_collector.storage.question_store import (
    delete_question,
    list_questions,
    save_question,
)

SERVICES = Question(
    name="services",
    prompt="Which services did you use today?",
    example="Mark all that apply",
    answer=AnswerSpec(
        ANSWER_TYPES.MANY_CHOICES,
        choices=(
            Choice("Food hamper", "food"),
            Choice("Clothing", "clothing"),
            Choice("Other", "other"),
        ),
    ),
)


def test_valid_question_has_no_errors() -> None:
    assert SERVICES.normalized().validation_errors(set()) == {}


def test_name_and_prompt_are_required() -> None:
    question = Question(name=" ", prompt="").normalized()

    assert set(question.validation_errors(set())) == {"name", "prompt"}


def test_names_are_unique_ignoring_case() -> None:
    errors = SERVICES.validation_errors({"SERVICES"})

    assert errors == {"name": 'Another question is already called "services".'}


def test_answer_errors_are_included() -> None:
    question = Question(
        name="q", prompt="?", answer=AnswerSpec(ANSWER_TYPES.ONE_CHOICE, choices=())
    )

    assert set(question.validation_errors(set())) == {"choices"}


def test_normalized_trims_text_and_choices() -> None:
    question = Question(
        name=" visit ",
        prompt=" First visit? ",
        example=" Mark one ",
        answer=AnswerSpec(
            ANSWER_TYPES.YES_NO, choices=(Choice(" Yes "), Choice("No", " n "))
        ),
    ).normalized()

    assert (question.name, question.prompt, question.example) == (
        "visit",
        "First visit?",
        "Mark one",
    )
    assert question.answer.choices == (Choice("Yes", "Yes"), Choice("No", "n"))


def test_saved_question_loads_back_unchanged(connection: sqlite3.Connection) -> None:
    written = Question(
        name="household_size",
        prompt="How many people live in your household?",
        answer=AnswerSpec(
            ANSWER_TYPES.WRITTEN,
            data_type=WRITTEN_DATA_TYPES.NUMBER,
            max_characters=2,
            number_minimum=1,
            number_maximum=20,
        ),
    )
    save_question(connection, SERVICES)
    save_question(connection, written)

    assert list_questions(connection) == [written, SERVICES]


def test_saving_again_updates_in_place(connection: sqlite3.Connection) -> None:
    save_question(connection, SERVICES)
    renamed = Question(
        name="services_used",
        prompt=SERVICES.prompt,
        answer=SERVICES.answer,
        question_id=SERVICES.question_id,
    )

    save_question(connection, renamed)

    assert list_questions(connection) == [renamed]


def test_database_rejects_duplicate_names(connection: sqlite3.Connection) -> None:
    save_question(connection, SERVICES)

    with pytest.raises(sqlite3.IntegrityError):
        save_question(connection, Question(name="SERVICES", prompt="?"))


def test_delete(connection: sqlite3.Connection) -> None:
    save_question(connection, SERVICES)

    delete_question(connection, SERVICES.question_id)

    assert list_questions(connection) == []
