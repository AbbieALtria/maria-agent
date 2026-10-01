"""Static appointment slots and callback-time parsing for the Phase 2 call tools.

Phase 2 availability is static: business days (Mon–Fri) at 10:00 and 14:00 in the prospect's
timezone, at least `min_lead_time_hours` ahead and at most `max_days_ahead` days ahead. Team
availability_rules replace this in Phase 4.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SLOT_TIMES = (time(10, 0), time(14, 0))
DEFAULT_DAYS = 3  # business days offered when the prospect has no preference
MAX_SLOTS = 4
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
PARTS = {
    "morning": (time(0), time(12)),
    "afternoon": (time(12), time(17)),
    "evening": (time(17), time(23, 59)),
}

# Callbacks may be scheduled outside the calling window, but only within 08:00–21:00 local.
CALLBACK_EARLIEST = time(8, 0)
CALLBACK_LATEST = time(21, 0)


@dataclass(frozen=True)
class Slot:
    start: datetime  # tz-aware, prospect timezone

    @property
    def label(self) -> str:
        return human_time(self.start)

    def as_dict(self) -> dict[str, str]:
        return {"start_iso": self.start.isoformat(), "label": self.label}


def human_time(dt: datetime) -> str:
    """'Friday, October 2 at 10:00 AM' (the LLM speaks it as words)."""
    hour = dt.strftime("%I").lstrip("0")
    return f"{dt.strftime('%A, %B')} {dt.day} at {hour}:{dt.strftime('%M %p')}"


def all_slots(
    now: datetime, tz: str, *, min_lead_time_hours: int = 24, max_days_ahead: int = 10
) -> list[Slot]:
    """Every valid static slot in the booking window, earliest first."""
    zone = ZoneInfo(tz)
    local_now = now.astimezone(zone)
    earliest = now + timedelta(hours=min_lead_time_hours)
    out = []
    for offset in range(1, max_days_ahead + 1):
        day = local_now.date() + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        for t in SLOT_TIMES:
            start = datetime.combine(day, t, tzinfo=zone)
            if start >= earliest:
                out.append(Slot(start))
    return out


def _parse_day(text: str, today: date) -> date | None:
    text = text.strip().lower()
    if not text:
        return None
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    for i, name in enumerate(WEEKDAYS):
        if name in text or text == name[:3]:
            # The next such day, never today ("friday" said on a Friday means next week).
            return today + timedelta(days=(i - today.weekday() - 1) % 7 + 1)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def offer_slots(
    now: datetime,
    tz: str,
    *,
    min_lead_time_hours: int = 24,
    max_days_ahead: int = 10,
    preferred_day: str | None = None,
    preferred_part_of_day: str | None = None,
    count: int | None = None,
) -> tuple[list[Slot], str | None]:
    """Slots to offer (≤ 4) and an optional note when the preference could not be met."""
    count = max(1, min(count or MAX_SLOTS, MAX_SLOTS))
    slots = all_slots(
        now, tz, min_lead_time_hours=min_lead_time_hours, max_days_ahead=max_days_ahead
    )
    note = None
    filtered = slots
    if preferred_day:
        day = _parse_day(preferred_day, now.astimezone(ZoneInfo(tz)).date())
        filtered = [s for s in filtered if s.start.date() == day] if day else []
        if not filtered:
            note = f"no slots on {preferred_day}; offering the earliest available instead"
    if preferred_part_of_day and filtered:
        lo, hi = PARTS.get(preferred_part_of_day.strip().lower(), (time(0), time(23, 59)))
        by_part = [s for s in filtered if lo <= s.start.time() < hi]
        if by_part:
            filtered = by_part
        else:
            note = f"no {preferred_part_of_day} slots; offering other times"
    if not filtered:
        filtered = slots
    if not preferred_day:
        days = sorted({s.start.date() for s in filtered})[:DEFAULT_DAYS]
        filtered = [s for s in filtered if s.start.date() in days]
    return filtered[:count], note


def match_slot(
    slot_start: str,
    now: datetime,
    tz: str,
    *,
    min_lead_time_hours: int = 24,
    max_days_ahead: int = 10,
) -> Slot | None:
    """The valid slot starting at `slot_start` (ISO; naive = prospect-local), else None."""
    try:
        start = datetime.fromisoformat(slot_start.strip())
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=ZoneInfo(tz))
    for s in all_slots(
        now, tz, min_lead_time_hours=min_lead_time_hours, max_days_ahead=max_days_ahead
    ):
        if s.start == start:
            return s
    return None


_REL_RE = re.compile(r"in\s+(\d+|an?|one|two|three|half an?)\s*(minute|min|hour|hr|day)s?")
_WORD_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}


def parse_callback_time(
    now: datetime, tz: str, *, when_iso: str | None = None, relative_text: str | None = None
) -> tuple[datetime, bool]:
    """Resolve a callback time in the prospect's timezone. Returns (when, understood)."""
    zone = ZoneInfo(tz)
    local_now = now.astimezone(zone)
    when: datetime | None = None
    if when_iso:
        try:
            when = datetime.fromisoformat(when_iso.strip())
            if when.tzinfo is None:
                when = when.replace(tzinfo=zone)
        except ValueError:
            when = None
    if when is None and relative_text:
        when = _parse_relative(relative_text.lower(), local_now)
    understood = when is not None
    if when is None:
        when = local_now + timedelta(hours=2)
    return _clamp_callback(when.astimezone(zone), local_now), understood


def _part_time(text: str, default: time) -> time:
    if "afternoon" in text:
        return time(14, 0)
    if "evening" in text or "tonight" in text:
        return time(18, 0)
    if "morning" in text:
        return time(10, 0)
    if "noon" in text or "lunch" in text:
        return time(12, 0)
    return default


def _parse_relative(text: str, local_now: datetime) -> datetime | None:
    zone = local_now.tzinfo
    m = _REL_RE.search(text)
    if m:
        qty, unit = m.groups()
        if qty.startswith("half"):
            return local_now + timedelta(minutes=30)
        n = int(qty) if qty.isdigit() else _WORD_NUM[qty]
        delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}
        return local_now + delta[unit[0]]
    today = local_now.date()
    if "tomorrow" in text:
        return datetime.combine(today + timedelta(days=1), _part_time(text, time(10)), zone)
    if "next week" in text:
        monday = today + timedelta(days=7 - today.weekday())
        return datetime.combine(monday, _part_time(text, time(10)), zone)
    if any(name in text for name in WEEKDAYS):
        day = _parse_day(text, today)
        if day:
            return datetime.combine(day, _part_time(text, time(10)), zone)
    if any(w in text for w in ("later today", "this afternoon", "this evening", "tonight")):
        default = time(15) if "later" in text else time(14)
        candidate = datetime.combine(today, _part_time(text, default), zone)
        return candidate if candidate > local_now else local_now + timedelta(hours=2)
    return None


def _clamp_callback(when: datetime, local_now: datetime) -> datetime:
    if when <= local_now:
        when = local_now + timedelta(hours=1)
    if when.time() < CALLBACK_EARLIEST:
        when = when.replace(hour=9, minute=0, second=0, microsecond=0)
    elif when.time() > CALLBACK_LATEST:
        when = (when + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return when
