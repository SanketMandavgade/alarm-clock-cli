"""Alarm state machine: wait -> ring -> (snooze -> wait ...) | done.

All side effects (clock, sleeping, sound, input, output) are injected so the
logic can be tested without real time passing.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

SNOOZE_WORDS = frozenset({"s", "snooze"})
DISMISS_WORDS = frozenset({"d", "dismiss", "stop", "q"})


class Outcome(enum.Enum):
    DISMISSED = "dismissed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class Settings:
    snooze: timedelta = timedelta(minutes=5)
    max_ring: timedelta = timedelta(minutes=5)
    tick: float = 1.0  # seconds between clock checks / rings (also bounds latency of commands)


def format_duration(delta: timedelta) -> str:
    total = max(0, int(round(delta.total_seconds())))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = [f"{v}{u}" for v, u in ((hours, "h"), (minutes, "m"), (seconds, "s")) if v]
    return " ".join(parts) or "0s"


def run_alarm(
    target: datetime,
    settings: Settings,
    *,
    now: Callable[[], datetime],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
    ring: Callable[[], None],
    poll: Callable[[], Optional[str]],
    say: Callable[[str], None],
    label: str = "Alarm",
) -> Outcome:
    """Run until the alarm is dismissed or times out. KeyboardInterrupt propagates.

    Two clocks, on purpose: ``now`` (wall clock) decides *when* to ring, so it
    follows clock changes and suspend; ``monotonic`` measures *how long* we have
    been ringing, so a clock change cannot shorten or extend the ring limit.
    """
    while True:
        _wait_until(target, settings.tick, now, sleep)
        say(
            f"{label}! Type 's' + Enter to snooze ({format_duration(settings.snooze)}), "
            "'d' + Enter to dismiss."
        )
        outcome = _ring(settings, monotonic, sleep, ring, poll, say)
        if outcome is not None:
            return outcome
        target = now() + settings.snooze
        say(f"Snoozed until {target:%H:%M:%S}.")


def _wait_until(target, tick, now, sleep) -> None:
    # Re-read the wall clock every tick rather than sleeping once for the whole
    # duration: survives system suspend and clock adjustments.
    while True:
        remaining = (target - now()).total_seconds()
        if remaining <= 0:
            return
        sleep(min(tick, remaining))


def _ring(settings, monotonic, sleep, ring, poll, say) -> Optional[Outcome]:
    """Ring until answered. Returns None if the user snoozed."""
    started = monotonic()
    limit = settings.max_ring.total_seconds()
    while True:
        ring()
        cmd = poll()
        if cmd in SNOOZE_WORDS:
            return None
        if cmd in DISMISS_WORDS:
            return Outcome.DISMISSED
        if cmd:
            say(f"Unrecognised command {cmd!r}. Use 's' or 'd'.")
        remaining = limit - (monotonic() - started)
        if remaining <= 0:
            say("Alarm timed out without being dismissed.")
            return Outcome.TIMED_OUT
        sleep(min(settings.tick, remaining))  # never sleep past the limit
