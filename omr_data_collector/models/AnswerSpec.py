from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

import jsonschema

from omr_data_collector.constants import (
    ANSWER_TYPES,
    CHECK_DIGIT_SCHEMES,
    DATE_TIME_DIGIT_LETTERS,
    DATE_TIME_FORMATS,
    LEGACY_DATE_TIME_FORMATS,
    MAX_CHOICES,
    MAX_WRITTEN_CHARACTERS,
    MIN_LIST_CHOICES,
    WRITTEN_DATA_TYPES,
    YES_NO_CHOICE_COUNT,
)
from omr_data_collector.i18n import tr
from omr_data_collector.schemas.answer_spec_schema import ANSWER_SPEC_SCHEMA

# How each date/time format is read when checking a keyed-in value.
STRPTIME_FORMATS = {
    "YYYY/MM/DD": "%Y/%m/%d",
    "HH:MM": "%H:%M",
    "YYYY/MM/DD HH:MM": "%Y/%m/%d %H:%M",
}
LIST_ANSWER_TYPES = {ANSWER_TYPES.ONE_CHOICE, ANSWER_TYPES.MANY_CHOICES}
CHOICE_ANSWER_TYPES = {ANSWER_TYPES.YES_NO, *LIST_ANSWER_TYPES}


@dataclass(frozen=True)
class Choice:
    """One bubble: the words printed beside it and the value saved when marked."""

    label: str
    output: str = ""


@dataclass(frozen=True)
class AnswerSpec:
    """How one answer is collected on paper and checked when read back.

    Shared by question blocks (wiki stories 40002-40006) and the columns of table
    blocks (30002-30006). Only the settings for ``answer_type`` matter; the others
    keep their values so switching type and back loses nothing.
    """

    answer_type: str
    choices: tuple[Choice, ...] = ()
    max_characters: int = 10
    data_type: str = WRITTEN_DATA_TYPES.FREE_TEXT
    number_minimum: int | None = None
    number_maximum: int | None = None
    date_time_format: str = DATE_TIME_FORMATS[0]
    check_digit: str = CHECK_DIGIT_SCHEMES.NONE

    @classmethod
    def default(cls, answer_type: str) -> AnswerSpec:
        """A starting point for a new answer of ``answer_type``."""
        if answer_type == ANSWER_TYPES.YES_NO:
            return cls(answer_type, choices=(Choice(tr("Yes")), Choice(tr("No"))))
        if answer_type in LIST_ANSWER_TYPES:
            return cls(answer_type, choices=(Choice(""),) * MIN_LIST_CHOICES)
        return cls(answer_type)

    def printed_choices(self) -> tuple[Choice, ...]:
        """The choices that get a bubble on paper.

        A yes/no answer is one bubble, marked or left empty: its first choice is
        printed and saved when marked, its second only saved when it is empty.
        """
        if self.answer_type == ANSWER_TYPES.YES_NO:
            return self.choices[:1]
        return self.choices

    def written_cells(self) -> tuple[str, ...] | None:
        """What each character position of a written answer gets on paper.

        ``""`` is a box for one handwritten character; any other string is
        printed there already (the ``/`` and ``:`` of dates and times, or a
        space between them). None means no boxes at all: free text is written
        on a line, or in its table cell, instead.
        """
        if self.answer_type != ANSWER_TYPES.WRITTEN:
            return ()
        if self.data_type == WRITTEN_DATA_TYPES.FREE_TEXT:
            return None
        if self.data_type == WRITTEN_DATA_TYPES.DATE_TIME:
            return tuple(
                "" if letter in DATE_TIME_DIGIT_LETTERS else letter
                for letter in self.date_time_format
            )
        return ("",) * self.max_characters

    def characters(self) -> int:
        """How many character widths a written answer takes on paper."""
        if self.data_type == WRITTEN_DATA_TYPES.DATE_TIME:
            return len(self.date_time_format)
        return self.max_characters

    def normalized(self) -> AnswerSpec:
        """Trim choice text; a choice saved as nothing is saved as its label.

        A date/time's length is set by its format, one box per character.
        """
        max_characters = self.max_characters
        if self.data_type == WRITTEN_DATA_TYPES.DATE_TIME:
            max_characters = len(self.date_time_format)
        choices = tuple(
            Choice(
                label=choice.label.strip(),
                output=choice.output.strip() or choice.label.strip(),
            )
            for choice in self.choices
        )
        return replace(self, choices=choices, max_characters=max_characters)

    def entry_error(self, values: tuple[str, ...]) -> str:
        """What is wrong with ``values`` as this answer's data, or "" if nothing.

        For checking what a person settled on when reviewing a captured sheet:
        choices must be this answer's saved values (one at most where only one is
        allowed); a written answer is one string, checked against its data type.
        Nothing at all (an unanswered question) is always allowed.
        """
        if not values or values == ("",):
            return ""
        if self.answer_type in CHOICE_ANSWER_TYPES:
            return self._choice_entry_error(values)
        (text,) = values
        if self.data_type == WRITTEN_DATA_TYPES.NUMBER:
            return self._number_entry_error(text)
        if self.data_type == WRITTEN_DATA_TYPES.DATE_TIME:
            return self._date_time_entry_error(text)
        if len(text) > self.max_characters:
            return tr("Use at most %n character(s).", None, self.max_characters)
        return ""

    def _choice_entry_error(self, values: tuple[str, ...]) -> str:
        outputs = {choice.output for choice in self.choices}
        if any(value not in outputs for value in values):
            return tr("Choose from this answer's choices.")
        if self.answer_type != ANSWER_TYPES.MANY_CHOICES and len(values) > 1:
            return tr("Only one choice is allowed.")
        return ""

    def _date_time_entry_error(self, text: str) -> str:
        try:
            datetime.strptime(text, STRPTIME_FORMATS[self.date_time_format])  # noqa: DTZ007 (a local date, as written)
        except ValueError:
            return tr("Enter a real date or time, written as {format}.").format(
                format=self.date_time_format
            )
        return ""

    def _number_entry_error(self, text: str) -> str:
        if not text.isdigit():
            return tr("Enter digits only.")
        number = int(text)
        if self.number_minimum is not None and number < self.number_minimum:
            return tr("Enter {minimum} or more.").format(minimum=self.number_minimum)
        if self.number_maximum is not None and number > self.number_maximum:
            return tr("Enter {maximum} or less.").format(maximum=self.number_maximum)
        return ""

    def validation_errors(self) -> dict[str, str]:
        """Map each invalid setting to a message for the person editing it.

        Meant for a normalized answer; an empty result means it can be saved.
        """
        if self.answer_type in CHOICE_ANSWER_TYPES:
            return self._choice_errors()
        if self.answer_type == ANSWER_TYPES.WRITTEN:
            return self._written_errors()
        return {"answer_type": tr("Choose an answer type.")}

    def to_dict(self) -> dict[str, Any]:
        """The JSON form stored in the database and copied into forms.

        Only the settings that apply to ``answer_type`` are written.
        """
        data: dict[str, Any] = {"answerType": self.answer_type}
        if self.answer_type in CHOICE_ANSWER_TYPES:
            data["choices"] = [
                {"label": choice.label, "output": choice.output}
                for choice in self.choices
            ]
            return data
        data["dataType"] = self.data_type
        if self.data_type == WRITTEN_DATA_TYPES.DATE_TIME:
            data["dateTimeFormat"] = self.date_time_format
            return data
        data["maxCharacters"] = self.max_characters
        if self.data_type == WRITTEN_DATA_TYPES.NUMBER:
            if self.number_minimum is not None:
                data["numberMinimum"] = self.number_minimum
            if self.number_maximum is not None:
                data["numberMaximum"] = self.number_maximum
        elif self.data_type == WRITTEN_DATA_TYPES.ID:
            data["checkDigit"] = self.check_digit
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnswerSpec:
        """Read the JSON form back.

        Raises:
            jsonschema.ValidationError: ``data`` isn't a stored answer.
        """
        if data.get("dateTimeFormat") in LEGACY_DATE_TIME_FORMATS:
            data = {
                **data,
                "dateTimeFormat": LEGACY_DATE_TIME_FORMATS[data["dateTimeFormat"]],
            }
        jsonschema.validate(instance=data, schema=ANSWER_SPEC_SCHEMA)
        defaults = cls(data["answerType"])
        spec = cls(
            answer_type=data["answerType"],
            choices=tuple(
                Choice(choice["label"], choice["output"])
                for choice in data.get("choices", [])
            ),
            max_characters=data.get("maxCharacters", defaults.max_characters),
            data_type=data.get("dataType", defaults.data_type),
            number_minimum=data.get("numberMinimum"),
            number_maximum=data.get("numberMaximum"),
            date_time_format=data.get("dateTimeFormat", defaults.date_time_format),
            check_digit=data.get("checkDigit", defaults.check_digit),
        )
        # Stored without a length when the format implies it.
        if spec.data_type == WRITTEN_DATA_TYPES.DATE_TIME:
            spec = replace(spec, max_characters=len(spec.date_time_format))
        return spec

    def _choice_errors(self) -> dict[str, str]:
        count = len(self.choices)
        if self.answer_type == ANSWER_TYPES.YES_NO and count != YES_NO_CHOICE_COUNT:
            return {"choices": tr("A yes/no answer has exactly two choices.")}
        if self.answer_type in LIST_ANSWER_TYPES and count < MIN_LIST_CHOICES:
            return {"choices": tr("Add at least %n choice(s).", None, MIN_LIST_CHOICES)}
        if count > MAX_CHOICES:
            return {"choices": tr("Use at most %n choice(s).", None, MAX_CHOICES)}

        for number, choice in enumerate(self.choices, start=1):
            if not choice.label:
                return {"choices": self._missing_words_message(number)}

        seen: dict[str, int] = {}
        for number, choice in enumerate(self.choices, start=1):
            key = choice.output.casefold()
            if key in seen:
                # The data couldn't tell these two marks apart.
                return {
                    "choices": tr(
                        'Choices {first} and {second} are both saved as "{value}"; '
                        "give each a different value."
                    ).format(first=seen[key], second=number, value=choice.output)
                }
            seen[key] = number
        return {}

    def _missing_words_message(self, number: int) -> str:
        if self.answer_type == ANSWER_TYPES.YES_NO:
            meaning = tr("Marked") if number == 1 else tr("Left empty")
            return tr('"{meaning}" needs words.').format(meaning=meaning)
        return tr("Choice {number} needs words to print.").format(number=number)

    def _written_errors(self) -> dict[str, str]:
        errors: dict[str, str] = {}
        if self.data_type not in WRITTEN_DATA_TYPES.values():
            errors["data_type"] = tr("Choose a data type.")
            return errors

        if self.data_type == WRITTEN_DATA_TYPES.DATE_TIME:
            if self.date_time_format not in DATE_TIME_FORMATS:
                errors["date_time_format"] = tr("Choose a date/time format.")
            return errors

        if not 1 <= self.max_characters <= MAX_WRITTEN_CHARACTERS:
            errors["max_characters"] = tr(
                "Use between 1 and %n character(s).", None, MAX_WRITTEN_CHARACTERS
            )

        if self.data_type == WRITTEN_DATA_TYPES.NUMBER:
            low, high = self.number_minimum, self.number_maximum
            if low is not None and high is not None and low > high:
                errors["number_maximum"] = tr(
                    "The maximum must be at least the minimum."
                )
        elif self.data_type == WRITTEN_DATA_TYPES.ID:
            if self.check_digit not in CHECK_DIGIT_SCHEMES.values():
                errors["check_digit"] = tr("Choose a check digit scheme.")
            elif (
                self.check_digit != CHECK_DIGIT_SCHEMES.NONE and self.max_characters < 2
            ):
                errors["max_characters"] = tr(
                    "An ID with a check digit needs at least 2 characters."
                )
        return errors
