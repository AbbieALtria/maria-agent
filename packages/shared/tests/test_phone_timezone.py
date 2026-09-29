import pytest

from maria_shared.phone import InvalidPhoneError, normalize_phone, region_of, try_normalize_phone
from maria_shared.timezone import infer_timezone, region_timezone


@pytest.mark.parametrize(
    ("raw", "region", "expected"),
    [
        ("(312) 555-0147", "US", "+13125550147"),
        ("312.555.0147", "us", "+13125550147"),
        ("+1 416 555 0199", None, "+14165550199"),
        ("0917 123 4567", "PH", "+639171234567"),
        ("+63 2 8123 4567", "US", "+63281234567"),
        ("0063 917 123 4567", None, "+639171234567"),
    ],
)
def test_normalize(raw: str, region: str | None, expected: str) -> None:
    assert normalize_phone(raw, region) == expected


@pytest.mark.parametrize("raw", ["", "abc", "12345", "555-0147", "+1 999 555 0147"])
def test_normalize_invalid(raw: str) -> None:
    with pytest.raises(InvalidPhoneError):
        normalize_phone(raw, "US")
    assert try_normalize_phone(raw, "US") is None


def test_region_of() -> None:
    assert region_of("+639171234567") == "PH"
    assert region_of("+14165550199") == "CA"


def test_region_timezone() -> None:
    assert region_timezone("US", "tx") == "America/Chicago"
    assert region_timezone("US", "New York") == "America/New_York"
    assert region_timezone("CA", "British Columbia") == "America/Vancouver"
    assert region_timezone(None, "ON") == "America/Toronto"
    assert region_timezone("PH", "Metro Manila") is None


def test_infer_timezone_order() -> None:
    # Address region beats phone area code (business moved / mobile number).
    assert infer_timezone("+12125550147", country="US", region="CA") == "America/Los_Angeles"
    # Phone area code when no region.
    assert infer_timezone("+13125550147") == "America/Chicago"
    assert infer_timezone("+16045550111", country="CA") == "America/Vancouver"
    # PH default.
    assert infer_timezone("+639171234567") == "Asia/Manila"
    assert infer_timezone(None, country="PH") == "Asia/Manila"
    # Fallback (campaign default) only when nothing else works.
    assert infer_timezone(None, fallback="America/Denver") == "America/Denver"
    assert infer_timezone(None, fallback="Not/AZone") is None
