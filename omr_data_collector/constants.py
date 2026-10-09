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
        "FORM": "form",
    },
    _dynamic=False,
)
QR_PAYLOAD_VERSION = 1

# Kept short because the name is encoded in every QR code; a longer payload means a
# denser code that is harder to read from a phone photo.
ORGANIZATION_NAME_MAX_LENGTH = 100

# Text blocks are picked by name in the form builder, so names stay list-sized.
TEXT_BLOCK_NAME_MAX_LENGTH = 100

QUESTION_NAME_MAX_LENGTH = 100

# How an answer is collected. Values are stored, so never rename one.
ANSWER_TYPES = DotMap(
    {
        "YES_NO": "YES_NO",
        "ONE_CHOICE": "ONE_CHOICE",
        "MANY_CHOICES": "MANY_CHOICES",
        "WRITTEN": "WRITTEN",
    },
    _dynamic=False,
)

# What a written answer must look like, checked when it is keyed in.
WRITTEN_DATA_TYPES = DotMap(
    {
        "FREE_TEXT": "FREE_TEXT",
        "NUMBER": "NUMBER",
        "DATE_TIME": "DATE_TIME",
        "ID": "ID",
    },
    _dynamic=False,
)

# Date/time answers are written in one of these fixed layouts, one character per
# printed box, so the layout also sets how many boxes are printed.
DATE_TIME_FORMATS = ("YYYY/MM/DD", "HH:MM", "YYYY/MM/DD HH:MM")
# Formats saved before dates used slashes, read as their slash versions: one
# character each, so a printed form's layout is unchanged.
LEGACY_DATE_TIME_FORMATS = {
    "YYYY-MM-DD": "YYYY/MM/DD",
    "YYYY-MM-DD HH:MM": "YYYY/MM/DD HH:MM",
}
# The letters in a date/time format that stand for a written digit; anything
# else (/ : and the space) is printed on the form already.
DATE_TIME_DIGIT_LETTERS = frozenset("YMDH")

CHECK_DIGIT_SCHEMES = DotMap(
    {
        "NONE": "NONE",
        "DAMM": "DAMM",
        "VERHOEFF": "VERHOEFF",
    },
    _dynamic=False,
)

YES_NO_CHOICE_COUNT = 2
# The stories ask for at least three choices for list answers; with fewer, a
# yes/no answer fits.
MIN_LIST_CHOICES = 3
# More bubbles than this no longer fit across a portrait page.
MAX_CHOICES = 20
MAX_WRITTEN_CHARACTERS = 60

TABLE_NAME_MAX_LENGTH = 100
# Column names become export column names, and are printed in a narrow header.
COLUMN_NAME_MAX_LENGTH = 40
DEFAULT_TABLE_ROWS = 10
MAX_TABLE_ROWS = 50

FORM_NAME_MAX_LENGTH = 100

# The kinds of block a form stacks down its pages. Values are stored.
BLOCK_KINDS = DotMap(
    {
        "TEXT": "TEXT",
        "QUESTION": "QUESTION",
        "TABLE": "TABLE",
    },
    _dynamic=False,
)

# What a table does when it doesn't fit in the space left on its page.
TABLE_BREAKS = DotMap(
    {
        "SPLIT": "SPLIT",
        "NEW_PAGE": "NEW_PAGE",
    },
    _dynamic=False,
)

# Where a captured sheet is in being turned into data (wiki 60001-60004).
CAPTURE_STATUSES = DotMap(
    {
        # Added, not read yet.
        "WAITING": "WAITING",
        # Its QR code or corner markers couldn't be read; Capture.problem says why.
        "UNREADABLE": "UNREADABLE",
        # Read, waiting for a person to check it against the image.
        "READ": "READ",
        # Checked and saved as data.
        "SAVED": "SAVED",
        # Checked and turned down: kept, but not part of the data.
        "REJECTED": "REJECTED",
    },
    _dynamic=False,
)
