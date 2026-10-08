from omr_data_collector.constants import (
    ORGANIZATION_NAME_MAX_LENGTH,
    QR_PAYLOAD_TYPES,
    QR_PAYLOAD_VERSION,
)

HEX_ID = {"type": "string", "pattern": "^[0-9a-f]{32}$"}

# The organization's own code: on its QR code page, saved or printed (wiki 20005).
ORGANIZATION_PAYLOAD_SCHEMA = {
    "type": "object",
    "required": ["type", "version", "organizationId", "name"],
    "additionalProperties": False,
    "properties": {
        "type": {"const": QR_PAYLOAD_TYPES.ORGANIZATION},
        "version": {
            "description": "Payload format version",
            "const": QR_PAYLOAD_VERSION,
        },
        "organizationId": {
            "description": "The organization's permanent ID (32 hex digits)",
            **HEX_ID,
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

# The code in every form page's top-right corner (wiki 50001): enough to find the
# exact stored version a scanned sheet was printed from, and so its OMR layout.
FORM_PAYLOAD_SCHEMA = {
    "type": "object",
    "required": ["type", "version", "organizationId", "formId", "formVersion", "page"],
    "additionalProperties": False,
    "properties": {
        "type": {"const": QR_PAYLOAD_TYPES.FORM},
        "version": {
            "description": "Payload format version",
            "const": QR_PAYLOAD_VERSION,
        },
        "organizationId": {"description": "Who made the form", **HEX_ID},
        "formId": {"description": "The form's permanent ID", **HEX_ID},
        "formVersion": {
            "description": "The stored version printed",
            "type": "integer",
            "minimum": 1,
        },
        "page": {
            "description": "Which page of the form, from 1",
            "type": "integer",
            "minimum": 1,
        },
    },
}

# Keys are camelCase to match OMRChecker's JSON files (template.json, config.json).
QR_PAYLOAD_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "QR Payload Schema",
    "description": "The JSON encoded in QR codes printed by OMR Data Collector. It "
    "carries only what identifies the source; contact details are printed as text "
    "beside the code, keeping the code small enough to read from a phone photo.",
    "oneOf": [ORGANIZATION_PAYLOAD_SCHEMA, FORM_PAYLOAD_SCHEMA],
}
