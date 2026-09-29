"""Phone normalization to E.164 (phonenumbers)."""

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat


class InvalidPhoneError(ValueError):
    pass


def normalize_phone(raw: str | None, default_region: str | None = None) -> str:
    """Return the E.164 form of `raw`, or raise InvalidPhoneError.

    `default_region` (ISO 3166 alpha-2, e.g. "US", "PH") is used for numbers written without
    a +country prefix; typically the lead's country column or the campaign's first country.
    """
    text = (raw or "").strip()
    if not text:
        raise InvalidPhoneError("empty phone number")
    region = default_region.upper() if default_region else None
    if text.startswith("00"):
        text = "+" + text[2:]
    try:
        parsed = phonenumbers.parse(text, region)
    except NumberParseException as exc:
        raise InvalidPhoneError(f"unparseable phone number: {exc}") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhoneError("not a valid phone number")
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)


def try_normalize_phone(raw: str | None, default_region: str | None = None) -> str | None:
    try:
        return normalize_phone(raw, default_region)
    except InvalidPhoneError:
        return None


def region_of(e164: str) -> str | None:
    """ISO country code for an E.164 number (e.g. "+63917..." → "PH")."""
    try:
        return phonenumbers.region_code_for_number(phonenumbers.parse(e164, None))
    except NumberParseException:
        return None
