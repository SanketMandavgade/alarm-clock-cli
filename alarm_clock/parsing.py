"""Turn user text into an alarm datetime. Pure functions, no I/O."""
from __future__ import annotations

import re
from datetime import datetime, timedelta


class ParseError(ValueError):
    """Raised when the time text is invalid."""


# re.ASCII: \d must not match other scripts' digits (int() would accept them).
_CLOCK_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(am|pm)?$", re.ASCII)
# \d{1,5}: bounded so int() and timedelta can never overflow on hostile input.
_REL_RE = re.compile(
    r"^(?:in\s+)?(?:(\d{1,5})\s*h)?\s*(?:(\d{1,5})\s*m)?\s*(?:(\d{1,5})\s*s)?$",
    re.ASCII,
)
MAX_RELATIVE = timedelta(hours=24)  # same horizon as an absolute time-of-day alarm

_HELP = "Use HH:MM, 7:30pm, or a duration such as 10m, 1h30m, 90s."


def parse_when(text: str, now: datetime) -> datetime:
    """Return the next datetime matching ``text``, strictly after ``now``."""
    text = " ".join(text.lower().split())

    m = _CLOCK_RE.match(text)
    if m:
        return _absolute(m, now, text)

    m = _REL_RE.match(text)
    if m and any(g is not None for g in m.groups()):
        hours, minutes, seconds = (int(g) if g else 0 for g in m.groups())
        delta = timedelta(hours=hours, minutes=minutes, seconds=seconds)
        if delta <= timedelta(0):
            raise ParseError("Duration must be greater than zero.")
        if delta > MAX_RELATIVE:
            raise ParseError("Duration must be 24h or less.")
        return now + delta

    raise ParseError(f"Unrecognised time {_shorten(text)!r}. {_HELP}")


def _shorten(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _absolute(m: re.Match, now: datetime, text: str) -> datetime:
    hour_s, minute_s, second_s, meridiem = m.groups()
    if minute_s is None and meridiem is None:
        raise ParseError(f"Ambiguous time {_shorten(text)!r}. {_HELP}")

    hour, minute, second = int(hour_s), int(minute_s or 0), int(second_s or 0)
    if meridiem:
        if not 1 <= hour <= 12:
            raise ParseError(f"Hour must be 1-12 with am/pm, got {hour}.")
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    elif not 0 <= hour <= 23:
        raise ParseError(f"Hour must be 0-23, got {hour}.")
    if not 0 <= minute <= 59:
        raise ParseError(f"Minute must be 0-59, got {minute}.")
    if not 0 <= second <= 59:
        raise ParseError(f"Second must be 0-59, got {second}.")

    target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target
