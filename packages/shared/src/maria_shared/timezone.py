"""Prospect timezone inference: address region (US state / CA province) → phone number → country
default (PH → Asia/Manila) → caller-supplied fallback (the campaign's default_timezone)."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import phonenumbers
from phonenumbers import NumberParseException
from phonenumbers import timezone as pn_timezone

# Primary timezone per US state / DC (states spanning two zones use the majority zone).
US_STATE_TZ: dict[str, str] = {
    "AL": "America/Chicago", "AK": "America/Anchorage", "AZ": "America/Phoenix",
    "AR": "America/Chicago", "CA": "America/Los_Angeles", "CO": "America/Denver",
    "CT": "America/New_York", "DE": "America/New_York", "DC": "America/New_York",
    "FL": "America/New_York", "GA": "America/New_York", "HI": "Pacific/Honolulu",
    "ID": "America/Boise", "IL": "America/Chicago", "IN": "America/Indiana/Indianapolis",
    "IA": "America/Chicago", "KS": "America/Chicago", "KY": "America/New_York",
    "LA": "America/Chicago", "ME": "America/New_York", "MD": "America/New_York",
    "MA": "America/New_York", "MI": "America/Detroit", "MN": "America/Chicago",
    "MS": "America/Chicago", "MO": "America/Chicago", "MT": "America/Denver",
    "NE": "America/Chicago", "NV": "America/Los_Angeles", "NH": "America/New_York",
    "NJ": "America/New_York", "NM": "America/Denver", "NY": "America/New_York",
    "NC": "America/New_York", "ND": "America/Chicago", "OH": "America/New_York",
    "OK": "America/Chicago", "OR": "America/Los_Angeles", "PA": "America/New_York",
    "RI": "America/New_York", "SC": "America/New_York", "SD": "America/Chicago",
    "TN": "America/Chicago", "TX": "America/Chicago", "UT": "America/Denver",
    "VT": "America/New_York", "VA": "America/New_York", "WA": "America/Los_Angeles",
    "WV": "America/New_York", "WI": "America/Chicago", "WY": "America/Denver",
    "PR": "America/Puerto_Rico",
}  # fmt: skip

CA_PROVINCE_TZ: dict[str, str] = {
    "AB": "America/Edmonton", "BC": "America/Vancouver", "MB": "America/Winnipeg",
    "NB": "America/Moncton", "NL": "America/St_Johns", "NS": "America/Halifax",
    "NT": "America/Yellowknife", "NU": "America/Iqaluit", "ON": "America/Toronto",
    "PE": "America/Halifax", "QC": "America/Toronto", "SK": "America/Regina",
    "YT": "America/Whitehorse",
}  # fmt: skip

US_STATE_NAMES: dict[str, str] = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL",
    "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA",
    "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA", "MICHIGAN": "MI",
    "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT",
    "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM", "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND",
    "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN",
    "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY", "PUERTO RICO": "PR",
}  # fmt: skip

CA_PROVINCE_NAMES: dict[str, str] = {
    "ALBERTA": "AB", "BRITISH COLUMBIA": "BC", "MANITOBA": "MB", "NEW BRUNSWICK": "NB",
    "NEWFOUNDLAND AND LABRADOR": "NL", "NEWFOUNDLAND": "NL", "NOVA SCOTIA": "NS",
    "NORTHWEST TERRITORIES": "NT", "NUNAVUT": "NU", "ONTARIO": "ON",
    "PRINCE EDWARD ISLAND": "PE", "QUEBEC": "QC", "QUÉBEC": "QC", "SASKATCHEWAN": "SK",
    "YUKON": "YT",
}  # fmt: skip

# Single-timezone (or conventionally single) countries.
COUNTRY_DEFAULT_TZ: dict[str, str] = {"PH": "Asia/Manila"}


def is_valid_timezone(name: str | None) -> bool:
    if not name:
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def region_timezone(country: str | None, region: str | None) -> str | None:
    """Timezone from a US state or Canadian province (code or full name)."""
    if not region:
        return None
    key = region.strip().upper().rstrip(".")
    country = (country or "").strip().upper() or None
    if country in (None, "US", "USA"):
        code = US_STATE_NAMES.get(key, key)
        if code in US_STATE_TZ:
            return US_STATE_TZ[code]
    if country in (None, "CA", "CAN"):
        code = CA_PROVINCE_NAMES.get(key, key)
        if code in CA_PROVINCE_TZ:
            return CA_PROVINCE_TZ[code]
    return None


def phone_timezone(e164: str | None) -> str | None:
    """Timezone from the phone number when it maps to exactly one zone."""
    if not e164:
        return None
    try:
        parsed = phonenumbers.parse(e164, None)
    except NumberParseException:
        return None
    zones = [z for z in pn_timezone.time_zones_for_number(parsed) if is_valid_timezone(z)]
    if len(zones) == 1:
        return zones[0]
    region = phonenumbers.region_code_for_number(parsed)
    return COUNTRY_DEFAULT_TZ.get(region or "")


def infer_timezone(
    e164: str | None,
    *,
    country: str | None = None,
    region: str | None = None,
    fallback: str | None = None,
) -> str | None:
    """Best-effort IANA timezone for a prospect."""
    tz = region_timezone(country, region)
    if tz:
        return tz
    tz = phone_timezone(e164)
    if tz:
        return tz
    if country and country.strip().upper() in COUNTRY_DEFAULT_TZ:
        return COUNTRY_DEFAULT_TZ[country.strip().upper()]
    return fallback if is_valid_timezone(fallback) else None
