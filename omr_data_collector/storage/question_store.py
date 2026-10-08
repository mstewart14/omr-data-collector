from __future__ import annotations

import json
from typing import TYPE_CHECKING

from omr_data_collector.models.AnswerSpec import AnswerSpec
from omr_data_collector.models.Question import Question

if TYPE_CHECKING:
    import sqlite3


def list_questions(connection: sqlite3.Connection) -> list[Question]:
    """Every saved question, sorted by name ignoring case."""
    rows = connection.execute(
        "SELECT question_id, name, prompt, example, answer FROM question"
        " ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [
        Question(
            question_id=row["question_id"],
            name=row["name"],
            prompt=row["prompt"],
            example=row["example"],
            answer=AnswerSpec.from_dict(json.loads(row["answer"])),
        )
        for row in rows
    ]


def save_question(connection: sqlite3.Connection, question: Question) -> None:
    """Insert the question, or update it if its ID is already stored.

    Raises:
        sqlite3.IntegrityError: Another question already has this name.
    """
    with connection:
        connection.execute(
            "INSERT INTO question (question_id, name, prompt, example, answer)"
            " VALUES (:question_id, :name, :prompt, :example, :answer)"
            " ON CONFLICT(question_id) DO UPDATE SET"
            " name = excluded.name, prompt = excluded.prompt,"
            " example = excluded.example, answer = excluded.answer,"
            " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
            {
                "question_id": question.question_id,
                "name": question.name,
                "prompt": question.prompt,
                "example": question.example,
                "answer": json.dumps(question.answer.to_dict()),
            },
        )


def delete_question(connection: sqlite3.Connection, question_id: str) -> None:
    with connection:
        connection.execute("DELETE FROM question WHERE question_id = ?", (question_id,))
