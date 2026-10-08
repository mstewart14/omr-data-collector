from omr_data_collector.constants import (
    ORGANIZATION_NAME_MAX_LENGTH,
    QR_PAYLOAD_TYPES,
    QR_PAYLOAD_VERSION,
)

# Keys are camelCase to match OMRChecker's JSON files (template.json, config.json).
QR_PAYLOAD_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "QR Payload Schema",
    "description": "The JSON encoded in QR codes printed by OMR Data Collector. It "
    "carries only what identifies the source; contact details are printed as text "
    "beside the code, keeping the code small enough to read from a phone photo.",
    "type": "object",
    "required": ["type", "version", "organizationId", "name"],
    "additionalProperties": False,
    "properties": {
        "type": {
            "description": "What the code identifies",
            "enum": [QR_PAYLOAD_TYPES.ORGANIZATION],
        },
        "version": {
            "description": "Payload format version",
            "const": QR_PAYLOAD_VERSION,
        },
        "organizationId": {
            "description": "The organization's permanent ID (32 hex digits)",
            "type": "string",
            "pattern": "^[0-9a-f]{32}$",
        },
        "name": {
            "description": "The organization's name when the code was generated",
            "type": "string",
            "minLength": 1,
            "maxLength": ORGANIZATION_NAME_MAX_LENGTH,
        },
        "url": {
            "description": "The organization's website, when it has one",
            "type": "string",
            "format": "uri",
        },
    },
}
