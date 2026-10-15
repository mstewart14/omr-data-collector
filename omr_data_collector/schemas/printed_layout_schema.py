from omr_data_collector.layout.omr_template import MARKER_FILE_NAME

# A printed version's page templates, as an imported form file carries them
# (form_transfer). OMRChecker is handed each page's template as it stands, so
# a file from elsewhere may only have the straightening steps this app writes,
# with the marker image it writes, and sizes no real page comes near: a crafted
# one could otherwise ask for an image too large to hold, or read another file
# as its marker. The rest of each template is checked by PageTemplate.from_dict
# and by OMRChecker itself.

# Pixels: far beyond any page at the app's template and processing scales (a
# Legal page is about 1600 by 2000), small enough to hold in memory.
PIXELS = {"type": "integer", "minimum": 1, "maximum": 5000}
SIZE = {"type": "array", "items": PIXELS, "minItems": 2, "maxItems": 2}
# More than any page could hold.
MAX_FIELD_BLOCKS = 5000
MAX_BUBBLE_TYPES = 500
MAX_PAGES = 100

STRAIGHTEN_ON_PAGE_EDGES = {
    "type": "object",
    "required": ["name", "options"],
    "additionalProperties": False,
    "properties": {
        "name": {"const": "CropPage"},
        "options": {
            "type": "object",
            "required": ["morphKernel", "processingImageShape"],
            "additionalProperties": False,
            "properties": {
                "morphKernel": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1, "maximum": 100},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "processingImageShape": SIZE,
            },
        },
    },
}

STRAIGHTEN_ON_MARKERS = {
    "type": "object",
    "required": ["name", "options"],
    "additionalProperties": False,
    "properties": {
        "name": {"const": "CropOnMarkers"},
        "options": {
            "type": "object",
            "required": [
                "type",
                "referenceImage",
                "markerDimensions",
                "processingImageShape",
                "defaultSelector",
            ],
            "additionalProperties": False,
            "properties": {
                "type": {"const": "FOUR_MARKERS"},
                "referenceImage": {"const": MARKER_FILE_NAME},
                "markerDimensions": SIZE,
                "processingImageShape": SIZE,
                "defaultSelector": {"const": "CENTERS"},
            },
        },
    },
}

PAGE_TEMPLATE_SCHEMA = {
    "type": "object",
    "required": ["templateDimensions", "bubbleDimensions", "preProcessors"],
    "properties": {
        "templateDimensions": SIZE,
        "bubbleDimensions": SIZE,
        "preProcessors": {
            "type": "array",
            "prefixItems": [STRAIGHTEN_ON_PAGE_EDGES, STRAIGHTEN_ON_MARKERS],
            "minItems": 2,
            "maxItems": 2,
        },
        "fieldBlocks": {"type": "object", "maxProperties": MAX_FIELD_BLOCKS},
        "customBubbleFieldTypes": {
            "type": "object",
            "maxProperties": MAX_BUBBLE_TYPES,
        },
    },
}

PRINTED_LAYOUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Printed Layout Schema",
    "type": "object",
    "required": ["pages"],
    "properties": {
        "pages": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_PAGES,
            "items": {
                "type": "object",
                "required": ["template", "fields"],
                "properties": {"template": PAGE_TEMPLATE_SCHEMA},
            },
        },
    },
}
