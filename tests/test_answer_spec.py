from __future__ import annotations

import jsonschema
import pytest

from omr_data_collector.constants import (
    ANSWER_TYPES,
    CHECK_DIGIT_SCHEMES,
    MAX_CHOICES,
    MAX_WRITTEN_CHARACTERS,
    WRITTEN_DATA_TYPES,
)
from omr_data_collector.models.AnswerSpec import AnswerSpec, Choice

YES_NO = ANSWER_TYPES.YES_NO
ONE = ANSWER_TYPES.ONE_CHOICE
MANY = ANSWER_TYPES.MANY_CHOICES
WRITTEN = ANSWER_TYPES.WRITTEN


def choices(*labels: str) -> tuple[Choice, ...]:
    return tuple(Choice(label) for label in labels)


def errors(spec: AnswerSpec) -> dict[str, str]:
    return spec.normalized().validation_errors()


def test_defaults_are_ready_to_fill_in() -> None:
    assert AnswerSpec.default(YES_NO).choices == (Choice("Yes"), Choice("No"))
    assert AnswerSpec.default(ONE).choices == choices("", "", "")
    assert AnswerSpec.default(WRITTEN).choices == ()


def test_blank_outputs_save_the_printed_words() -> None:
    spec = AnswerSpec(ONE, choices=(Choice(" Food hamper ", ""), Choice("Other", "x")))

    assert spec.normalized().choices == (
        Choice("Food hamper", "Food hamper"),
        Choice("Other", "x"),
    )


def test_yes_no_needs_exactly_two_choices() -> None:
    assert errors(AnswerSpec(YES_NO, choices=choices("Yes", "No"))) == {}
    assert set(errors(AnswerSpec(YES_NO, choices=choices("Yes", "No", "Maybe")))) == {
        "choices"
    }


@pytest.mark.parametrize("answer_type", [ONE, MANY])
def test_lists_need_at_least_three_choices(answer_type: str) -> None:
    assert errors(AnswerSpec(answer_type, choices=choices("A", "B", "C"))) == {}
    assert errors(AnswerSpec(answer_type, choices=choices("A", "B"))) == {
        "choices": "Add at least 3 choices."
    }


def test_lists_are_capped_at_what_fits_on_a_page() -> None:
    labels = [f"Choice {number}" for number in range(MAX_CHOICES + 1)]

    assert set(errors(AnswerSpec(ONE, choices=choices(*labels)))) == {"choices"}


def test_every_choice_needs_printed_words() -> None:
    assert errors(AnswerSpec(ONE, choices=choices("A", " ", "C"))) == {
        "choices": "Choice 2 needs words to print."
    }


def test_choices_must_save_distinct_values() -> None:
    spec = AnswerSpec(
        ONE, choices=(Choice("Food"), Choice("Clothes"), Choice("Meal", "FOOD"))
    )

    assert errors(spec) == {
        "choices": 'Choices 1 and 3 are both saved as "FOOD"; give each a different value.'
    }


def test_written_characters_are_limited() -> None:
    assert errors(AnswerSpec(WRITTEN, max_characters=MAX_WRITTEN_CHARACTERS)) == {}
    assert set(errors(AnswerSpec(WRITTEN, max_characters=0))) == {"max_characters"}
    assert set(
        errors(AnswerSpec(WRITTEN, max_characters=MAX_WRITTEN_CHARACTERS + 1))
    ) == {"max_characters"}


def test_number_range_must_be_in_order() -> None:
    number = WRITTEN_DATA_TYPES.NUMBER

    assert errors(AnswerSpec(WRITTEN, data_type=number, number_minimum=1)) == {}
    assert set(
        errors(
            AnswerSpec(WRITTEN, data_type=number, number_minimum=5, number_maximum=1)
        )
    ) == {"number_maximum"}


def test_date_time_format_sets_the_box_count() -> None:
    spec = AnswerSpec(
        WRITTEN,
        data_type=WRITTEN_DATA_TYPES.DATE_TIME,
        date_time_format="YYYY-MM-DD HH:MM",
        max_characters=3,
    )

    assert spec.characters() == 16
    assert errors(spec) == {}


def test_ids_with_a_check_digit_need_room_for_it() -> None:
    spec = AnswerSpec(
        WRITTEN,
        data_type=WRITTEN_DATA_TYPES.ID,
        check_digit=CHECK_DIGIT_SCHEMES.DAMM,
        max_characters=1,
    )

    assert set(errors(spec)) == {"max_characters"}


@pytest.mark.parametrize(
    "spec",
    [
        AnswerSpec(YES_NO, choices=(Choice("Yes", "1"), Choice("No", "0"))),
        AnswerSpec(
            MANY, choices=(Choice("A", "a"), Choice("B", "b"), Choice("C", "c"))
        ),
        AnswerSpec(WRITTEN, max_characters=25),
        AnswerSpec(
            WRITTEN,
            data_type=WRITTEN_DATA_TYPES.NUMBER,
            max_characters=3,
            number_minimum=0,
            number_maximum=120,
        ),
        AnswerSpec(
            WRITTEN, data_type=WRITTEN_DATA_TYPES.DATE_TIME, date_time_format="HH:MM"
        ),
        AnswerSpec(
            WRITTEN,
            data_type=WRITTEN_DATA_TYPES.ID,
            max_characters=6,
            check_digit=CHECK_DIGIT_SCHEMES.VERHOEFF,
        ),
    ],
)
def test_json_round_trips(spec: AnswerSpec) -> None:
    # Stored answers are normalized (a date/time's length comes from its format).
    assert AnswerSpec.from_dict(spec.to_dict()) == spec.normalized()


def test_json_keeps_only_the_settings_that_apply() -> None:
    spec = AnswerSpec(
        YES_NO,
        choices=(Choice("Yes", "Yes"), Choice("No", "No")),
        max_characters=40,
        data_type=WRITTEN_DATA_TYPES.NUMBER,
    )

    assert spec.to_dict() == {
        "answerType": "YES_NO",
        "choices": [{"label": "Yes", "output": "Yes"}, {"label": "No", "output": "No"}],
    }


@pytest.mark.parametrize(
    "data",
    [
        {"answerType": "ESSAY"},
        {"answerType": "WRITTEN", "maxCharacters": 0},
        {"answerType": "ONE_CHOICE", "choices": [{"label": "A"}]},
        {"answerType": "WRITTEN", "colour": "red"},
    ],
)
def test_from_dict_rejects_malformed_answers(data: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        AnswerSpec.from_dict(data)
