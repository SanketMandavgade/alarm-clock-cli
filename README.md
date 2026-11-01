# alarm_clock

A foreground command-line alarm clock. Python 3.8+, standard library only: no web UI, no database, no third-party packages.

## Setup

No installation. Clone or unzip, then run from the project root:

```bash
python -m alarm_clock 07:30
```

## Usage

```bash
python -m alarm_clock 07:30              # 24h time
python -m alarm_clock 7:30pm             # 12h time ("7pm" also works)
python -m alarm_clock 1h30m              # relative duration
python -m alarm_clock in 10m --label "Tea" --snooze 2 --max-ring 120
```

### Time formats

| Form | Examples | Notes |
|---|---|---|
| 24h clock | `07:30`, `7:30`, `07:30:15` | hour 0-23 |
| 12h clock | `7:30pm`, `7pm`, `12:00am` | hour 1-12; `12am` = midnight |
| Duration | `90s`, `10m`, `1h30m`, `in 5m` | h/m/s, at most 24h, must be > 0 |

A bare number (`7`) is rejected as ambiguous. If a time of day has already passed today (or equals "now") the alarm is set for **tomorrow**; the full date is always printed on start.

### Options

| Option | Default | Meaning |
|---|---|---|
| `--label TEXT` | `Alarm` | Message shown when ringing |
| `--snooze MIN` | `5` | Snooze length in minutes (0 < MIN <= 1440) |
| `--max-ring SEC` | `300` | Stop ringing after this many seconds (0 < SEC <= 86400) |

### Behaviour

- **Ringing:** prints a message and sounds the terminal bell plus a native sound where available (`winsound` beep on Windows, `afplay` on macOS, `paplay` / `canberra-gtk-play` on Linux), once per second.
- **Snooze:** type `s` + Enter. Rings again after `--snooze` minutes; repeatable without limit.
- **Dismiss:** type `d` + Enter. Unrecognised input is reported and ignored.
- **Timeout:** each ringing episode stops after `--max-ring` seconds if unanswered.
- **Cancel:** Ctrl+C or SIGTERM, while waiting or ringing.
- **Input typed before the alarm rings** stays queued and is applied when it rings (a pre-typed `d` dismisses immediately). This also makes `echo d | python -m alarm_clock 5s` work.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Dismissed |
| 2 | Invalid time or option (message on stderr) |
| 3 | Rang for `--max-ring` without being dismissed |
| 130 | Cancelled (Ctrl+C / SIGTERM) |

## Tests

```bash
python -m unittest discover -s tests -v      # everything: 56 tests, ~5 s on Linux
python -m unittest tests.test_parsing tests.test_engine tests.test_cli tests.test_sound
                                             # fast unit tests only: 50 tests, no real processes
```

On Windows, 10 of the 56 tests are skipped by design (see below), so the full run reports `OK (skipped=10)`.

| Module | Kind |
|---|---|
| `test_parsing`, `test_engine`, `test_cli`, `test_sound` | Deterministic unit tests. Clock, sleep, sound, input and output are injected; nothing really sleeps. Some `test_sound` cases start a throwaway child process or exercise the subprocess player path; they are skipped on Windows. |
| `test_process` | Runs `python -m alarm_clock` as a real subprocess: SIGINT/SIGTERM while waiting and ringing, dismiss via stdin, EOF, invalid input. Takes a few seconds of real time; runs with an empty `PATH` so no native audio plays. Skipped on Windows. |

## Design

```
parsing.py   text -> datetime            pure, no I/O
engine.py    wait / ring / snooze loop   all side effects injected
sound.py     Ringer                      native player if found, always terminal bell
cli.py       argparse + wiring           stdin read on a daemon thread
__main__.py  entry point                 routes SIGTERM into the Ctrl+C path
```

Key decisions:

- **Dependency injection with plain callables** (`now`, `monotonic`, `sleep`, `ring`, `poll`, `say`) rather than classes or ABCs: the engine is tested with a fake clock in milliseconds.
- **Two clocks.** The alarm *time* is wall-clock (`now`), re-checked every <=1 s, so a forward clock change or suspend rings promptly and a backward change keeps waiting for the new wall time. The *ring limit* uses a monotonic clock, so a clock change can neither cut it short nor make it ring forever.
- **Ringing is bounded:** never sleeps past `--max-ring`.
- **Cleanup cannot mask errors:** `Ringer.close()` does terminate, bounded wait, then kill, and never raises, because it runs in `finally`.
- **One cancel path:** SIGTERM raises `KeyboardInterrupt`; the announcement, player/stdin setup and the run loop sit inside one `try`, so cancelling there exits 130 with the player stopped.
- **Strict input validation:** ASCII digits only, digit runs bounded, relative durations capped at 24 h, option ranges bounded, so no input can reach an overflow.
- **Sound is best-effort:** the terminal bell always fires; a missing or failing player is silently dropped.

## Known limitations and unverified behaviour

Verified, Linux (container, no audio device): the full test suite and real-process smoke tests on Python 3.8.20 and 3.12.3.

Verified, Windows (build 26100, PowerShell 5.1, Python 3.11.4), run by hand:
- Full suite: 56 tests, 46 passed, 10 skipped by design (`test_process` and the POSIX-only sound tests), 0 failures.
- Dismiss (exit 0), Ctrl+C while waiting (exit 130, no traceback), invalid input (exit 2), max-ring timeout (exit 3), and the README time formats (`7:30pm`, `1h30m`, `in 3s`).
- Snooze, by driving the real process over stdin from a script (rang, snoozed, rang again, dismissed, exit 0).
- The `winsound` beep was audible.

Not verified:
- **macOS** was not run at all, and the `afplay` path is untested.
- **Linux native audio** (`paplay`, `canberra-gtk-play`) is untested: the container had no audio device, so only the bell character was emitted.
- **On Windows**, SIGTERM terminates the process outright, so only Ctrl+C is a graceful cancel; this was not tested, and the real-process tests (`test_process`) are skipped there. Terminals may also mute the bell.

Design limitations:
- One alarm per process, no persistence: if the process dies the alarm is gone.
- Local naive time, no timezone/DST handling: across a DST change the alarm fires at the wall-clock reading, which may differ by an hour of elapsed time.
- Commands need Enter (line-buffered stdin).
- If stdin is closed or at EOF the alarm cannot be dismissed; it rings until `--max-ring` and exits 3.
- Whether time spent suspended counts toward `--max-ring` depends on the OS's monotonic clock.
- A snooze does not cut off a sound clip already playing; it finishes by itself. Exiting stops it.
- A signal in the few milliseconds of start-up before the alarm is announced is not handled gracefully.
- Hours/minutes/seconds only: no "noon", weekdays or dates.