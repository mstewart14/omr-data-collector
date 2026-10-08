from __future__ import annotations

import pytest

from omr_data_collector.constants import ORGANIZATION_NAME_MAX_LENGTH
from omr_data_collector.models.Organization import Organization


def test_new_organizations_get_distinct_permanent_ids() -> None:
    first, second = Organization(name="A"), Organization(name="B")

    assert len(first.organization_id) == 32
    assert first.organization_id != second.organization_id


def test_normalized_trims_fields_and_adds_url_scheme() -> None:
    organization = Organization(
        name="  Food Bank ",
        phone=" 613-555-0123 ",
        address="  1 Main St\nOttawa  ",
        url=" example.org ",
        email=" info@example.org ",
    )

    normalized = organization.normalized()

    assert normalized.name == "Food Bank"
    assert normalized.phone == "613-555-0123"
    assert normalized.address == "1 Main St\nOttawa"
    assert normalized.url == "https://example.org"
    assert normalized.email == "info@example.org"
    assert normalized.organization_id == organization.organization_id


def test_normalized_keeps_an_existing_url_scheme() -> None:
    assert Organization(name="A", url="http://example.org").normalized().url == (
        "http://example.org"
    )


def test_only_the_name_is_required() -> None:
    assert Organization(name="Food Bank").validation_errors() == {}
    assert set(Organization(name="").validation_errors()) == {"name"}


def test_name_length_is_limited() -> None:
    too_long = Organization(name="x" * (ORGANIZATION_NAME_MAX_LENGTH + 1))

    assert set(too_long.validation_errors()) == {"name"}


@pytest.mark.parametrize(
    "phone",
    ["613-555-0123", "+1 (613) 555-0123", "613.555.0123", "613 555 0123 ext. 42"],
)
def test_accepts_common_phone_formats(phone: str) -> None:
    assert Organization(name="A", phone=phone).validation_errors() == {}


@pytest.mark.parametrize("phone", ["555-012", "call us", "613-555-0123 or 0124"])
def test_rejects_phone_typos(phone: str) -> None:
    assert set(Organization(name="A", phone=phone).validation_errors()) == {"phone"}


@pytest.mark.parametrize("url", ["https://example", "ftp://example.org", "https://"])
def test_rejects_invalid_urls(url: str) -> None:
    assert set(Organization(name="A", url=url).validation_errors()) == {"url"}


@pytest.mark.parametrize("email", ["info", "info@example", "in fo@example.org"])
def test_rejects_invalid_emails(email: str) -> None:
    assert set(Organization(name="A", email=email).validation_errors()) == {"email"}


def test_rejects_unknown_page_layout_values() -> None:
    organization = Organization(name="A", paper_size="B5", orientation="SIDEWAYS")

    assert set(organization.validation_errors()) == {"paper_size", "orientation"}
