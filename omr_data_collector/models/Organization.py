from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace
from urllib.parse import urlparse

from omr_data_collector.constants import (
    ORGANIZATION_NAME_MAX_LENGTH,
    PAGE_ORIENTATIONS,
    PAPER_SIZES,
)
from omr_data_collector.i18n import tr

# Deliberately loose: these catch typos, not every invalid address. The email
# pattern only insists on something@something.something.
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_REGEX = re.compile(r"^\+?[0-9 ().-]+(\s*(x|ext\.?)\s*[0-9]+)?$", re.IGNORECASE)
PHONE_MIN_DIGITS = 7


@dataclass(frozen=True)
class Organization:
    """The service provider that produces the forms (wiki story 20001).

    ``organization_id`` never changes once created, so forms printed before a rename
    still identify the same organization.
    """

    name: str
    phone: str = ""
    address: str = ""
    url: str = ""
    email: str = ""
    paper_size: str = PAPER_SIZES.LETTER
    orientation: str = PAGE_ORIENTATIONS.PORTRAIT
    organization_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def normalized(self) -> Organization:
        """Return a copy with surrounding whitespace removed and a URL scheme added."""
        url = self.url.strip()
        if url and "://" not in url:
            url = f"https://{url}"
        return replace(
            self,
            name=self.name.strip(),
            phone=self.phone.strip(),
            address=self.address.strip(),
            url=url,
            email=self.email.strip(),
        )

    def validation_errors(self) -> dict[str, str]:
        """Map each invalid field's name to a message for the person entering it.

        Meant for a normalized organization; an empty result means it can be saved.
        """
        errors: dict[str, str] = {}

        if not self.name:
            errors["name"] = tr("Enter the organization's name.")
        elif len(self.name) > ORGANIZATION_NAME_MAX_LENGTH:
            errors["name"] = tr(
                "Keep the name to %n character(s) or fewer.",
                None,
                ORGANIZATION_NAME_MAX_LENGTH,
            )

        if self.phone:
            digit_count = sum(character.isdigit() for character in self.phone)
            if not PHONE_REGEX.match(self.phone) or digit_count < PHONE_MIN_DIGITS:
                errors["phone"] = tr("Enter a phone number, like 613-555-0123.")

        if self.url:
            parsed_url = urlparse(self.url)
            if (
                parsed_url.scheme not in {"http", "https"}
                or "." not in parsed_url.netloc
            ):
                errors["url"] = tr("Enter a web address, like example.org.")

        if self.email and not EMAIL_REGEX.match(self.email):
            errors["email"] = tr("Enter an email address, like info@example.org.")

        if self.paper_size not in PAPER_SIZES.values():
            errors["paper_size"] = tr("Choose a paper size.")

        if self.orientation not in PAGE_ORIENTATIONS.values():
            errors["orientation"] = tr("Choose an orientation.")

        return errors
