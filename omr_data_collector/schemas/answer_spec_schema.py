from omr_data_collector.constants import (
    ANSWER_TYPES,
    CHECK_DIGIT_SCHEMES,
    DATE_TIME_FORMATS,
    MAX_CHOICES,
    MAX_WRITTEN_CHARACTERS,
    WRITTEN_DATA_TYPES,
)

# Keys are camelCase to match OMRChecker's JSON files (template.json, config.json).
# This is the shape stored in the database and copied into forms; AnswerSpec's
# validation_errors adds the rules a person editing it needs explained (minimum
# choice counts, distinct outputs, number ranges).
ANSWER_SPEC_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Answer Spec Schema",
    "description": "How one answer is collected on paper and checked when read back",
    "type": "object",
    "required": ["answerType"],
    "additionalProperties": False,
    "properties": {
        "answerType": {"enum": list(ANSWER_TYPES.values())},
        "choices": {
            "description": "The bubbles, in printed order",
            "type": "array",
            "maxItems": MAX_CHOICES,
            "items": {
                "type": "object",
                "required": ["label", "output"],
                "additionalProperties": False,
                "properties": {
                    "label": {
                        "description": "Printed beside the bubble",
                        "type": "string",
                    },
                    "output": {"description": "Saved when marked", "type": "string"},
                },
            },
        },
        "dataType": {"enum": list(WRITTEN_DATA_TYPES.values())},
        "maxCharacters": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_WRITTEN_CHARACTERS,
        },
        "numberMinimum": {"type": "integer"},
        "numberMaximum": {"type": "integer"},
        "dateTimeFormat": {"enum": list(DATE_TIME_FORMATS)},
        "checkDigit": {"enum": list(CHECK_DIGIT_SCHEMES.values())},
    },
}
