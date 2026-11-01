import io
import sys
import threading
import unittest
from contextlib import redirect_stderr
from unittest import mock

from alarm_clock.cli import (EXIT_CANCELLED, EXIT_ERROR, EXIT_OK, EXIT_TIMED_OUT,
                             StdinCommands, main)
from tests.test_engine import FakeClock


def run(argv, commands=(), sleep=None, out=None):
    clock = FakeClock()
    cmds = iter(commands)
    lines, rings = [], []
    code = main(argv, now=clock.now, monotonic=clock.monotonic, sleep=sleep or clock.sleep,
                ring=lambda: rings.append(1), poll=lambda: next(cmds, None),
                out=out or lines.append)
    return code, lines, rings


class CliTests(unittest.TestCase):
    def test_invalid_time_exit_code_and_message(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code, lines, rings = run(["25:99"])
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("error:", err.getvalue())
        self.assertEqual(rings, [])

    def test_happy_path_prints_full_date(self):
        code, lines, rings = run(["1m", "--label", "Standup"], ["d"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("Alarm set for Thu 2026-10-22 07:01:00 (in 1m)", lines[0])
        self.assertTrue(any(l.startswith("Standup!") for l in lines))

    def test_in_prefix_as_separate_args(self):
        code, lines, _ = run(["in", "2m"], ["d"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("(in 2m)", lines[0])

    def test_timeout_exit_code(self):
        code, _, _ = run(["1s", "--max-ring", "2"])
        self.assertEqual(code, EXIT_TIMED_OUT)

    def test_cancel_while_waiting(self):
        def interrupt(_):
            raise KeyboardInterrupt

        code, lines, rings = run(["5m"], sleep=interrupt)
        self.assertEqual(code, EXIT_CANCELLED)
        self.assertEqual(lines[-1], "Alarm cancelled.")
        self.assertEqual(rings, [])

    def test_cancel_signal_right_after_announcement_is_still_clean(self):
        # Regression: the announcement used to sit outside the try block, so a
        # signal landing there escaped as a traceback instead of exit 130.
        seen = []

        def out(msg):
            seen.append(msg)
            if len(seen) == 1:
                raise KeyboardInterrupt

        code, _, rings = run(["5m"], out=out)
        self.assertEqual(code, EXIT_CANCELLED)
        self.assertEqual(seen[-1], "Alarm cancelled.")
        self.assertEqual(rings, [])

    def test_out_of_range_options_rejected_cleanly(self):
        for argv in (["5m", "--snooze", "1e308"], ["5m", "--max-ring", "1e308"],
                     ["5m", "--snooze", "0"], ["5m", "--snooze", "-1"], ["5m", "--snooze", "nan"],
                     ["5m", "--snooze", "abc"], ["5m", "--bogus"], []):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    run(argv)
                self.assertEqual(ctx.exception.code, 2)

    def test_snooze_flag_is_used(self):
        code, lines, _ = run(["1s", "--snooze", "2"], ["s", "d"])
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(any("Snoozed until 07:02:01" in l for l in lines))


def drain(cmds):
    """Wait for the reader thread to finish (join, not sleep), then collect commands."""
    if cmds._thread is not None:
        cmds._thread.join(timeout=5)
        assert not cmds._thread.is_alive()
    got = []
    while True:
        c = cmds.poll()
        if c is None:
            return got
        got.append(c)


class StdinCommandsTests(unittest.TestCase):
    def test_lines_are_normalised(self):
        self.assertEqual(drain(StdinCommands(io.StringIO("S\n  d \n"))), ["s", "d"])

    def test_input_typed_before_ringing_is_kept(self):
        # Documented behaviour: queued input is applied when the alarm rings.
        self.assertEqual(drain(StdinCommands(io.StringIO("d\n"))), ["d"])

    def test_eof_yields_no_commands(self):
        self.assertEqual(drain(StdinCommands(io.StringIO(""))), [])

    def test_poll_does_not_block_when_empty(self):
        cmds = StdinCommands(io.StringIO(""))
        drain(cmds)
        self.assertIsNone(cmds.poll())

    def test_closed_stdin_fd_means_no_thread_and_no_commands(self):
        # With file descriptor 0 closed, sys.stdin is None.
        with mock.patch.object(sys, "stdin", None):
            cmds = StdinCommands()
        self.assertIsNone(cmds._thread)
        self.assertIsNone(cmds.poll())

    def test_unreadable_stdin_is_eof_not_a_thread_traceback(self):
        class Broken:
            def __iter__(self):
                raise ValueError("I/O operation on closed file")

        crashes = []
        with mock.patch.object(threading, "excepthook", crashes.append):
            self.assertEqual(drain(StdinCommands(Broken())), [])
        self.assertEqual(crashes, [])

    def test_undecodable_bytes_are_eof_not_a_thread_traceback(self):
        stream = io.TextIOWrapper(io.BytesIO(b"\xff\xfe\n"), encoding="utf-8", errors="strict")
        crashes = []
        with mock.patch.object(threading, "excepthook", crashes.append):
            drain(StdinCommands(stream))
        self.assertEqual(crashes, [])


if __name__ == "__main__":
    unittest.main()
