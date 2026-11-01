"""Argument parsing and wiring. Everything slow or external is injectable."""
from __future__ import annotations

import argparse
import math
import queue
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, List, Optional

from .engine import Outcome, Settings, format_duration, run_alarm
from .parsing import ParseError, parse_when
from .sound import Ringer

EXIT_OK, EXIT_ERROR, EXIT_TIMED_OUT, EXIT_CANCELLED = 0, 2, 3, 130


class StdinCommands:
    """Reads lines from stdin on a daemon thread so ringing never blocks on input.

    Lines typed before the alarm rings stay queued and are applied when it rings.
    A closed, unreadable or exhausted stdin simply yields no further commands.
    """

    def __init__(self, stream=None) -> None:
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        if stream is None:
            stream = sys.stdin  # None when file descriptor 0 is closed
        if stream is not None:
            self._thread = threading.Thread(target=self._read, args=(stream,), daemon=True)
            self._thread.start()

    def _read(self, stream) -> None:
        try:
            for line in stream:
                self._queue.put(line.strip().lower())
        except (OSError, ValueError):
            pass  # closed/undecodable stdin: behave like EOF instead of a thread traceback

    def poll(self) -> Optional[str]:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None


def _bounded_float(maximum: float) -> Callable[[str], float]:
    def convert(text: str) -> float:
        try:
            value = float(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"not a number: {text!r}")
        if not math.isfinite(value) or not 0 < value <= maximum:
            raise argparse.ArgumentTypeError(f"must be greater than 0 and at most {maximum:g}")
        return value

    return convert


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="alarm_clock",
        description="Foreground CLI alarm clock.",
        epilog="Examples: alarm_clock 07:30 | alarm_clock 7:30pm | alarm_clock in 10m",
    )
    p.add_argument("when", nargs="+", help="HH:MM, h:MMam/pm, or a duration (10m, 1h30m, 90s)")
    p.add_argument("--label", default="Alarm", help="message shown when ringing")
    p.add_argument("--snooze", type=_bounded_float(1440), default=5.0, metavar="MIN",
                   help="snooze length in minutes (default 5)")
    p.add_argument("--max-ring", type=_bounded_float(86400), default=300.0, metavar="SEC",
                   help="stop ringing after this many seconds (default 300)")
    return p


def main(
    argv: Optional[List[str]] = None,
    *,
    now: Callable[[], datetime] = datetime.now,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    ring: Optional[Callable[[], None]] = None,
    poll: Optional[Callable[[], Optional[str]]] = None,
    out: Optional[Callable[[str], None]] = None,
) -> int:
    args = build_parser().parse_args(argv)
    out = out or (lambda msg: print(msg, flush=True))

    current = now()
    try:
        target = parse_when(" ".join(args.when), current)
    except ParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    settings = Settings(
        snooze=timedelta(minutes=args.snooze),
        max_ring=timedelta(seconds=args.max_ring),
    )
    ringer = None
    try:
        # Everything that can be interrupted lives inside the try, so a signal
        # at any point after parsing is a clean cancel (exit 130), not a traceback.
        out(f"Alarm set for {target:%a %Y-%m-%d %H:%M:%S} "
            f"(in {format_duration(target - current)}). Ctrl+C to cancel.")
        if ring is None:
            ring = ringer = Ringer()
        if poll is None:
            poll = StdinCommands().poll
        outcome = run_alarm(target, settings, now=now, monotonic=monotonic, sleep=sleep,
                            ring=ring, poll=poll, say=out, label=args.label)
    except KeyboardInterrupt:
        out("Alarm cancelled.")
        return EXIT_CANCELLED
    finally:
        if ringer is not None:
            ringer.close()
    return EXIT_OK if outcome is Outcome.DISMISSED else EXIT_TIMED_OUT
