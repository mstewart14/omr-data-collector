from __future__ import annotations

import json
from typing import TYPE_CHECKING

import cv2
import numpy as np
import pytest

from omr_data_collector.identity.qr_code import (
    build_form_payload,
    build_organization_payload,
    make_qr_code,
    parse_payload,
    qr_code_png,
    read_qr_codes,
    save_qr_code,
)
from omr_data_collector.models.Organization import Organization

if TYPE_CHECKING:
    from pathlib import Path

ORGANIZATION = Organization(
    name="Banque alimentaire d'Orléans",
    phone="613-555-0123",
    address="1 Main St",
    url="https://example.org",
    email="info@example.org",
)


def decode_png(png: bytes) -> str:
    image = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    assert image is not None
    (text,) = read_qr_codes(image)
    return text


def test_payload_identifies_the_organization_without_contact_details() -> None:
    payload = json.loads(build_organization_payload(ORGANIZATION))

    assert payload == {
        "type": "organization",
        "version": 1,
        "organizationId": ORGANIZATION.organization_id,
        "name": "Banque alimentaire d'Orléans",
        "url": "https://example.org",
    }


def test_payload_is_ascii_so_accents_survive_any_reader() -> None:
    assert build_organization_payload(ORGANIZATION).isascii()


def test_payload_leaves_out_an_empty_url() -> None:
    payload = json.loads(build_organization_payload(Organization(name="Food Bank")))

    assert "url" not in payload


def test_generated_code_scans_back_to_the_same_payload() -> None:
    # The same reader scanning uses, so this is the round trip a scanned form makes.
    payload = build_organization_payload(ORGANIZATION)

    scanned = decode_png(qr_code_png(make_qr_code(payload), scale=4))

    assert parse_payload(scanned) == json.loads(payload)


@pytest.mark.parametrize(
    "text",
    [
        "https://example.org",
        '{"type": "organization", "version": 1}',
        '{"type": "organization", "version": 99, "organizationId": "'
        + "0" * 32
        + '", "name": "A"}',
    ],
)
def test_parse_payload_rejects_other_codes(text: str) -> None:
    with pytest.raises(ValueError, match="Not an OMR Data Collector QR code"):
        parse_payload(text)


@pytest.mark.parametrize("suffix", [".png", ".svg", ".pdf"])
def test_saves_in_each_supported_format(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"qr{suffix}"

    save_qr_code(make_qr_code(build_organization_payload(ORGANIZATION)), path)

    assert path.stat().st_size > 0


def test_saved_png_scans(tmp_path: Path) -> None:
    path = tmp_path / "qr.png"
    payload = build_organization_payload(ORGANIZATION)

    save_qr_code(make_qr_code(payload), path)

    assert decode_png(path.read_bytes()) == payload


def test_refuses_unsupported_formats(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.gif"):
        save_qr_code(make_qr_code("x"), tmp_path / "qr.gif")


def test_a_form_page_code_is_compact_and_reads_back() -> None:
    organization_id, form_id = "0" * 31 + "1", "f" * 32

    text = build_form_payload(organization_id, form_id, 3, 2)

    assert text.startswith("OMR1/")
    assert len(text) <= 60
    # Alphanumeric mode and a version 3 symbol: big squares for its size.
    code = make_qr_code(text)
    assert code.mode == "alphanumeric"
    assert code.version == 3
    assert parse_payload(text) == {
        "type": "form",
        "version": 1,
        "organizationId": organization_id,
        "formId": form_id,
        "formVersion": 3,
        "page": 2,
    }


def test_form_codes_printed_as_json_still_read() -> None:
    printed = (
        '{"type":"form","version":1,"organizationId":"' + "a" * 32 + '",'
        '"formId":"' + "b" * 32 + '","formVersion":1,"page":1}'
    )

    assert parse_payload(printed)["formId"] == "b" * 32


@pytest.mark.parametrize(
    "text",
    ["OMR1/ABC/DEF/1/1", "OMR1/" + "Z" * 25 + "/" + "Z" * 25 + "/1/1", "OMR1/x/y/z"],
)
def test_a_broken_compact_code_is_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="Not an OMR Data Collector QR code"):
        parse_payload(text)
