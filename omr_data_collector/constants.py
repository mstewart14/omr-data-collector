from dotmap import DotMap

DATABASE_FILENAME = "omr-data-collector.sqlite3"

PAPER_SIZES = DotMap(
    {
        "LETTER": "LETTER",
        "LEGAL": "LEGAL",
        "A4": "A4",
    },
    _dynamic=False,
)

PAGE_ORIENTATIONS = DotMap(
    {
        "PORTRAIT": "PORTRAIT",
        "LANDSCAPE": "LANDSCAPE",
    },
    _dynamic=False,
)

# What a QR code printed by this app identifies, and the payload format version, so
# that a scanner can tell our codes apart from anything else and handle old prints.
QR_PAYLOAD_TYPES = DotMap(
    {
        "ORGANIZATION": "organization",
    },
    _dynamic=False,
)
QR_PAYLOAD_VERSION = 1

# Kept short because the name is encoded in every QR code; a longer payload means a
# denser code that is harder to read from a phone photo.
ORGANIZATION_NAME_MAX_LENGTH = 100
