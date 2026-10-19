from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# The base size every form printed in before forms had a font of their own. The
# layout's other text (examples, answer labels, table headings) keeps its size
# relative to it, so a 12 pt form prints all of them 12/10 as big.
STANDARD_SIZE = 10.0
MIN_SIZE = 8.0
# Bigger and answer labels outgrow their rows, which are a fixed height so the
# bubbles in them stay where the scanner expects.
MAX_SIZE = 14.0
SIZES = (8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0)


@dataclass(frozen=True)
class FormFont:
    """The typeface and size a form's text prints in, chosen in its form details.

    ``family`` is a font installed on the computer, or "" for its standard font
    (what every form used before this was chosen, and still the default).
    ``style`` is one of the family's own styles ("Light", "Medium"...), or "" for
    its regular one. Bold and italic from the text editor apply on top.
    """

    family: str = ""
    style: str = ""
    size: float = STANDARD_SIZE

    @property
    def scale(self) -> float:
        """How much bigger than the standard size the form's text is."""
        return self.size / STANDARD_SIZE

    def is_standard(self) -> bool:
        return self == FormFont()

    def to_dict(self) -> dict[str, Any]:
        return {"family": self.family, "style": self.style, "size": self.size}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> FormFont:
        """Read a stored font back; a definition from before fonts has none."""
        if data is None:
            return cls()
        return cls(family=data["family"], style=data["style"], size=float(data["size"]))
