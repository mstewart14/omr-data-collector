from omr_data_collector.constants import (
    BLOCK_KINDS,
    FORM_NAME_MAX_LENGTH,
    PAGE_ORIENTATIONS,
    TABLE_BREAKS,
)

# One stored version of a form: everything needed to print it again, or to scan
# sheets printed from it. Keys are camelCase to match OMRChecker's JSON files. Each
# block's content is checked again by its own type when it is read (the answer and
# table-column schemas).
FORM_DEFINITION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Form Definition Schema",
    "type": "object",
    "required": ["name", "orientation", "blocks"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "maxLength": FORM_NAME_MAX_LENGTH},
        "orientation": {"enum": list(PAGE_ORIENTATIONS.values())},
        "font": {
            "description": "The typeface and base size of the form's text; left "
            "out for the computer's standard font at 10 pt",
            "type": "object",
            "required": ["family", "style", "size"],
            "additionalProperties": False,
            "properties": {
                "family": {
                    "description": "An installed font family, or empty for the "
                    "computer's standard font",
                    "type": "string",
                    "maxLength": 200,
                },
                "style": {
                    "description": "One of the family's styles, or empty for its "
                    "regular one",
                    "type": "string",
                    "maxLength": 200,
                },
                "size": {"type": "number", "minimum": 1, "maximum": 100},
            },
        },
        "blocks": {
            "description": "Stacked top to bottom, in order",
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "blockId",
                    "kind",
                    "sourceId",
                    "startOnNewPage",
                    "tableBreak",
                    "content",
                ],
                "additionalProperties": False,
                "properties": {
                    "blockId": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
                    "kind": {"enum": list(BLOCK_KINDS.values())},
                    "sourceId": {
                        "description": "The library block copied, or null if written "
                        "on the form",
                        "type": ["string", "null"],
                    },
                    "startOnNewPage": {"type": "boolean"},
                    "tableBreak": {"enum": list(TABLE_BREAKS.values())},
                    "content": {"type": "object"},
                },
            },
        },
    },
}
