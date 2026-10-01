from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from app.dialer.slots import all_slots, match_slot, offer_slots, parse_callback_time

NY = "America/New_York"
# Thursday 2026-10-01 09:05 New York (13:05 UTC)
NOW = datetime(2026, 10, 1, 13, 5, tzinfo=UTC)


def test_all_slots_business_days_and_lead_time() -> None:
    slots = all_slots(NOW, NY, min_lead_time_hours=24, max_days_ahead=10)
    local = [s.start for s in slots]
    assert all(d.weekday() < 5 for d in local)
    assert {d.time() for d in local} == {time(10), time(14)}
    # Fri 10:00 is < 24h away? No: Fri 10:00 NY is 24h55m after now → allowed.
    assert local[0] == datetime(2026, 10, 2, 10, 0, tzinfo=ZoneInfo(NY))
    assert local[2].date().isoformat() == "2026-10-05"  # weekend skipped


def test_lead_time_excludes_early_slots() -> None:
    slots = all_slots(NOW, NY, min_lead_time_hours=26, max_days_ahead=10)
    assert slots[0].start.hour == 14 and slots[0].start.day == 2


def test_offer_default_three_business_days() -> None:
    slots, note = offer_slots(NOW, NY, count=4)
    assert note is None and len(slots) == 4
    days = {s.start.date() for s in slots}
    assert len(days) <= 3
    assert slots[0].label == "Friday, October 2 at 10:00 AM"


def test_offer_preferences() -> None:
    slots, note = offer_slots(NOW, NY, preferred_day="tuesday", preferred_part_of_day="afternoon")
    assert note is None
    assert [(s.start.date().isoformat(), s.start.hour) for s in slots] == [("2026-10-06", 14)]
    slots, note = offer_slots(NOW, NY, preferred_day="saturday")
    assert note and slots  # falls back to the earliest
    slots, _ = offer_slots(NOW, NY, preferred_day="2026-10-07")
    assert {s.start.day for s in slots} == {7}


def test_match_slot() -> None:
    assert match_slot("2026-10-02T10:00:00-04:00", NOW, NY) is not None
    assert match_slot("2026-10-02T14:00:00", NOW, NY) is not None  # naive = prospect-local
    assert match_slot("2026-10-02T14:00:00Z", NOW, NY).start.hour == 10  # same instant as 10 NY
    assert match_slot("2026-10-02T11:00:00-04:00", NOW, NY) is None
    assert match_slot("garbage", NOW, NY) is None
    assert match_slot("2026-10-03T10:00:00-04:00", NOW, NY) is None  # Saturday


def test_callback_parsing() -> None:
    def cb(**kw):
        when, ok = parse_callback_time(NOW, NY, **kw)
        return when.astimezone(ZoneInfo(NY)).strftime("%a %H:%M"), ok

    assert cb(relative_text="tomorrow afternoon") == ("Fri 14:00", True)
    assert cb(relative_text="in 2 hours") == ("Thu 11:05", True)
    assert cb(relative_text="call me Monday") == ("Mon 10:00", True)
    assert cb(relative_text="later today") == ("Thu 15:00", True)
    assert cb(relative_text="whenever") == ("Thu 11:05", False)
    assert cb(when_iso="2026-10-01T23:30:00-04:00") == ("Fri 09:00", True)  # clamped to 08–21
    assert cb(when_iso="2026-10-01T06:00:00-04:00") == ("Thu 10:05", True)  # past → +1h
