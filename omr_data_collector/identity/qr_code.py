from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any

import cv2
import jsonschema
import segno

from omr_data_collector.constants import QR_PAYLOAD_TYPES, QR_PAYLOAD_VERSION
from omr_data_collector.i18n import tr
from omr_data_collector.schemas.qr_payload_schema import QR_PAYLOAD_SCHEMA

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np

    from omr_data_collector.models.Organization import Organization

# Medium error correction survives about 15% damage (a fold, a smudge, glare) without
# making the code much denser than the lowest level would.
QR_ERROR_CORRECTION = "m"
# The quiet zone the QR standard requires around the code, in modules.
QR_BORDER_MODULES = 4

SAVE_FILE_FORMATS = {".png", ".svg", ".pdf"}

# A form page's compact code starts with this, and its format version.
FORM_PAYLOAD_PREFIX = "OMR1"
BASE36_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# A 128-bit ID takes 25 base 36 digits.
BASE36_ID_LENGTH = 25


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
    # OMRChecker's barcode fields use, turns UTF-8 "é" into Shift-JIS), whereas
    # JSON's \u escapes read back the same everywhere.
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def build_form_payload(
    organization_id: str, form_id: str, form_version: int, page: int
) -> str:
    """The QR code for one page of one printed version of a form.

    Compact, to keep the code's squares big enough to read from an ordinary
    phone photo: ``OMR1/<organization>/<form>/<version>/<page>``, the two IDs
    in base 36. Upper-case letters, digits and "/" are QR's alphanumeric mode,
    which packs them tightly: the whole code is a version 3 symbol, 29 squares
    wide, where the same in JSON took 49. The page number lets a scanned sheet
    be matched to its page even when the pages come back shuffled.
    """
    return "/".join(
        (
            FORM_PAYLOAD_PREFIX,
            _base36(organization_id),
            _base36(form_id),
            str(form_version),
            str(page),
        )
    )


def parse_payload(text: str) -> dict[str, Any]:
    """Decode the text read from one of our QR codes.

    A form page's compact code becomes the same dictionary as the JSON one
    printed before it (which is still read), so callers needn't know which.

    Raises:
        ValueError: The text isn't a payload this app produces.
    """
    if text.startswith(f"{FORM_PAYLOAD_PREFIX}/"):
        return _parse_compact_form_payload(text)
    try:
        payload = json.loads(text)
        jsonschema.validate(instance=payload, schema=QR_PAYLOAD_SCHEMA)
    except (json.JSONDecodeError, jsonschema.ValidationError) as error:
        msg = tr("Not an OMR Data Collector QR code")
        raise ValueError(msg) from error
    return payload


def _parse_compact_form_payload(text: str) -> dict[str, Any]:
    parts = text.split("/")
    try:
        _, organization, form, version, page = parts
        payload = {
            "type": QR_PAYLOAD_TYPES.FORM,
            "version": QR_PAYLOAD_VERSION,
            "organizationId": _hex_id(organization),
            "formId": _hex_id(form),
            "formVersion": int(version),
            "page": int(page),
        }
        jsonschema.validate(instance=payload, schema=QR_PAYLOAD_SCHEMA)
    except (ValueError, jsonschema.ValidationError) as error:
        msg = tr("Not an OMR Data Collector QR code")
        raise ValueError(msg) from error
    return payload


def _base36(hex_id: str) -> str:
    """A 32-hex-digit ID in base 36: 25 upper-case letters and digits."""
    number = int(hex_id, 16)
    digits = ""
    while number:
        number, digit = divmod(number, 36)
        digits = BASE36_DIGITS[digit] + digits
    return digits.rjust(BASE36_ID_LENGTH, "0")


def _hex_id(base36: str) -> str:
    """Back from base 36 to the ID's 32 hex digits.

    Raises:
        ValueError: Not a base 36 ID of the right length.
    """
    # Only ever caught, by parse_payload: these errors need no message.
    if len(base36) != BASE36_ID_LENGTH or any(c not in BASE36_DIGITS for c in base36):
        raise ValueError
    number = int(base36, 36)
    if number >= 16**32:
        raise ValueError
    return f"{number:032x}"


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
        msg = tr("Can't save a QR code as '{suffix}'; use .png, .svg or .pdf.").format(
            suffix=suffix
        )
        raise ValueError(msg)
    # 10 pixels per module keeps a PNG sharp when it is enlarged for printing; SVG
    # and PDF are vector, so the scale only sets their nominal size.
    qr_code.save(str(path), scale=10, border=QR_BORDER_MODULES)


def read_qr_codes(image: np.ndarray) -> list[str]:
    """The text of every QR code found in a grayscale or colour image.

    OpenCV's WeChat reader (in the contrib build the app already needs) reads
    blurred, small and unevenly lit photos that zbar and OpenCV's standard
    detector miss, and needs no system library, so installers don't have to
    bundle zbar.
    """
    return [text for text, _ in find_qr_codes(image)]


def find_qr_codes(image: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """Every QR code found, with its four corners in the image's pixels.

    The corners are in the code's own order (top-left, top-right, bottom-right,
    bottom-left), however the image is turned, so they show which way up it is.
    """
    texts, points = cv2.wechat_qrcode.WeChatQRCode().detectAndDecode(image)
    return list(zip(texts, points, strict=True))
