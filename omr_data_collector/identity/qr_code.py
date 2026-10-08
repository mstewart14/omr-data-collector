from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any

import jsonschema
import segno

from omr_data_collector.constants import QR_PAYLOAD_TYPES, QR_PAYLOAD_VERSION
from omr_data_collector.schemas.qr_payload_schema import QR_PAYLOAD_SCHEMA

if TYPE_CHECKING:
    from pathlib import Path

    from omr_data_collector.models.Organization import Organization

# Medium error correction survives about 15% damage (a fold, a smudge, glare) without
# making the code much denser than the lowest level would.
QR_ERROR_CORRECTION = "m"
# The quiet zone the QR standard requires around the code, in modules.
QR_BORDER_MODULES = 4

SAVE_FILE_FORMATS = {".png", ".svg", ".pdf"}


def build_organization_payload(organization: Organization) -> str:
    payload: dict[str, Any] = {
        "type": QR_PAYLOAD_TYPES.ORGANIZATION,
        "version": QR_PAYLOAD_VERSION,
        "organizationId": organization.organization_id,
        "name": organization.name,
    }
    if organization.url:
        payload["url"] = organization.url
    # Compact separators: every byte saved keeps the printed code less dense. ASCII
    # only: QR codes carry bytes, and readers guess their text encoding (zbar, which
    # OMRChecker uses, turns UTF-8 "é" into Shift-JIS), whereas JSON's \u escapes
    # read back the same everywhere.
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def build_form_payload(
    organization_id: str, form_id: str, form_version: int, page: int
) -> str:
    """The QR code for one page of one printed version of a form.

    The page number lets a scanned sheet be matched to its page of the template
    even when the pages of a multi-page form come back shuffled.
    """
    payload = {
        "type": QR_PAYLOAD_TYPES.FORM,
        "version": QR_PAYLOAD_VERSION,
        "organizationId": organization_id,
        "formId": form_id,
        "formVersion": form_version,
        "page": page,
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def parse_payload(text: str) -> dict[str, Any]:
    """Decode the text read from one of our QR codes.

    Raises:
        ValueError: The text isn't a payload this app produces.
    """
    try:
        payload = json.loads(text)
        jsonschema.validate(instance=payload, schema=QR_PAYLOAD_SCHEMA)
    except (json.JSONDecodeError, jsonschema.ValidationError) as error:
        msg = "Not an OMR Data Collector QR code"
        raise ValueError(msg) from error
    return payload


def make_qr_code(payload: str) -> segno.QRCode:
    return segno.make_qr(payload, error=QR_ERROR_CORRECTION, boost_error=False)


def qr_code_png(qr_code: segno.QRCode, scale: int) -> bytes:
    """Render as PNG, ``scale`` pixels per module, including the quiet zone."""
    buffer = io.BytesIO()
    qr_code.save(buffer, kind="png", scale=scale, border=QR_BORDER_MODULES)
    return buffer.getvalue()


def save_qr_code(qr_code: segno.QRCode, path: Path) -> None:
    """Save as PNG, SVG or PDF, chosen by the file extension.

    Raises:
        ValueError: The extension isn't one of ``SAVE_FILE_FORMATS``.
    """
    suffix = path.suffix.lower()
    if suffix not in SAVE_FILE_FORMATS:
        msg = f"Can't save a QR code as '{suffix}'; use .png, .svg or .pdf."
        raise ValueError(msg)
    # 10 pixels per module keeps a PNG sharp when it is enlarged for printing; SVG
    # and PDF are vector, so the scale only sets their nominal size.
    qr_code.save(str(path), scale=10, border=QR_BORDER_MODULES)
