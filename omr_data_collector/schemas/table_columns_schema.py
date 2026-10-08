from omr_data_collector.constants import COLUMN_NAME_MAX_LENGTH
from omr_data_collector.schemas.answer_spec_schema import ANSWER_SPEC_SCHEMA

# The columns of a table block, as stored in the database and copied into forms.
TABLE_COLUMNS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Table Columns Schema",
    "description": "The columns of a table block, in printed order",
    "type": "array",
    "items": {
        "type": "object",
        "required": ["name", "example", "answer"],
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string", "maxLength": COLUMN_NAME_MAX_LENGTH},
            "example": {"type": "string"},
            "answer": ANSWER_SPEC_SCHEMA,
        },
    },
}
