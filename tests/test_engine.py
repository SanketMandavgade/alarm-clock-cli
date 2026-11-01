import unittest
from datetime import datetime, timedelta

from alarm_clock.engine import Outcome, Settings, format_duration, run_alarm

START = datetime(2026, 10, 22, 7, 0, 0)


class FakeClock:
    """Fake wall + monotonic clocks.

    sleep() advances both by the requested time. ``wall_steps`` maps the n-th
    sleep call (1-based) to an extra wall-clock step in seconds, simulating a
    manual/NTP change (or suspend) that the monotonic clock does not see.
    """

    def __init__(self, wall_steps=None):
        self.wall = START
        self.mono = 0.0
        self.sleeps = []
        self._steps = dict(wall_steps or {})

    def now(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.mono += seconds
        extra = self._steps.get(len(self.sleeps), 0.0)
        self.wall += timedelta(seconds=seconds + extra)


class Harness:
    def __init__(self, commands=(), clock=None, **settings):
        self.clock = clock or FakeClock()
        self.rings = 0
        self.said = []
        self._cmds = iter(commands)
        self.settings = Settings(**settings)

    def _ring(self):
        self.rings += 1

    def run(self, target):
        return run_alarm(
            target, self.settings,
            now=self.clock.now, monotonic=self.clock.monotonic, sleep=self.clock.sleep,
            ring=self._ring, poll=lambda: next(self._cmds, None), say=self.said.append,
        )


class WaitingPhase(unittest.TestCase):
    def test_waits_in_ticks_without_overshooting(self):
        h = Harness(["d"])
        h.run(START + timedelta(seconds=2.5))
        self.assertEqual(h.clock.sleeps, [1.0, 1.0, 0.5])
        self.assertEqual(h.clock.now(), START + timedelta(seconds=2.5))

    def test_target_in_past_rings_immediately(self):
        h = Harness(["d"])
        h.run(START - timedelta(minutes=1))
        self.assertEqual(h.clock.sleeps, [])
        self.assertEqual(h.rings, 1)

    def test_wall_clock_jump_forward_rings_promptly(self):
        # e.g. laptop suspended: the first sleep "takes" two extra hours
        h = Harness(["d"], clock=FakeClock(wall_steps={1: 7200}))
        h.run(START + timedelta(hours=1))
        self.assertEqual(len(h.clock.sleeps), 1)
        self.assertEqual(h.rings, 1)

    def test_wall_clock_jump_backward_waits_for_wall_target(self):
        # Alarm is a wall-clock time, so if the clock is set back it keeps waiting
        # until the (new) wall clock reaches the target. Rings exactly once, on time.
        target = START + timedelta(seconds=10)
        h = Harness(["d"], clock=FakeClock(wall_steps={2: -100}))
        h.run(target)
        self.assertEqual(h.rings, 1)
        self.assertEqual(h.clock.now(), target)
        self.assertEqual(len(h.clock.sleeps), 2 + 108)  # 2 before the step, 108 after

    def test_keyboard_interrupt_propagates(self):
        h = Harness()

        def boom(_):
            raise KeyboardInterrupt

        h.clock.sleep = boom
        with self.assertRaises(KeyboardInterrupt):
            h.run(START + timedelta(minutes=1))


class RingingPhase(unittest.TestCase):
    def test_dismiss_on_first_ring(self):
        h = Harness(["d"])
        self.assertIs(h.run(START + timedelta(seconds=1)), Outcome.DISMISSED)
        self.assertEqual(h.rings, 1)

    def test_snooze_then_dismiss(self):
        h = Harness(["s", "d"], snooze=timedelta(seconds=60))
        outcome = h.run(START + timedelta(seconds=3))
        self.assertIs(outcome, Outcome.DISMISSED)
        self.assertEqual(h.rings, 2)
        self.assertEqual(h.clock.now(), START + timedelta(seconds=63))
        self.assertTrue(any("Snoozed until 07:01:03" in m for m in h.said))

    def test_unknown_command_ignored_and_reported(self):
        h = Harness(["x", "d"])
        self.assertIs(h.run(START), Outcome.DISMISSED)
        self.assertEqual(h.rings, 2)
        self.assertTrue(any("Unrecognised" in m for m in h.said))

    def test_times_out_when_never_dismissed(self):
        h = Harness([], max_ring=timedelta(seconds=3))
        self.assertIs(h.run(START), Outcome.TIMED_OUT)
        self.assertEqual(h.rings, 4)  # at t=0,1,2,3
        self.assertEqual(h.clock.mono, 3.0)

    def test_ring_never_outlasts_max_ring_even_if_shorter_than_tick(self):
        h = Harness([], max_ring=timedelta(seconds=0.5))
        self.assertIs(h.run(START), Outcome.TIMED_OUT)
        self.assertEqual(h.clock.mono, 0.5)  # previously overshot to a full tick (1.0)
        self.assertEqual(h.rings, 2)

    def test_wall_clock_step_back_while_ringing_still_times_out(self):
        # Regression: elapsed ring time used to be measured on the wall clock, so
        # a backwards step meant the alarm kept ringing far beyond max_ring.
        h = Harness([], clock=FakeClock(wall_steps={2: -3600}), max_ring=timedelta(seconds=3))
        self.assertIs(h.run(START), Outcome.TIMED_OUT)
        self.assertEqual(h.rings, 4)
        self.assertEqual(len(h.clock.sleeps), 3)
        self.assertEqual(h.clock.mono, 3.0)

    def test_wall_clock_step_forward_while_ringing_does_not_cut_it_short(self):
        # e.g. suspend/resume or a forward clock correction during ringing
        h = Harness([], clock=FakeClock(wall_steps={2: 7200}), max_ring=timedelta(seconds=3))
        self.assertIs(h.run(START), Outcome.TIMED_OUT)
        self.assertEqual(h.rings, 4)
        self.assertEqual(h.clock.mono, 3.0)

    def test_snooze_counts_from_when_it_was_pressed_not_from_the_target(self):
        # The alarm rings late (clock stepped forward past the target, e.g. after
        # suspend). Snooze must last a full minute from *now*, not from the old target.
        h = Harness(["s", "d"], clock=FakeClock(wall_steps={1: 600}),
                    snooze=timedelta(seconds=60))
        self.assertIs(h.run(START + timedelta(seconds=5)), Outcome.DISMISSED)
        rang_at = START + timedelta(seconds=601)  # 1s tick + 600s step
        self.assertTrue(any("Snoozed until 07:11:01" in m for m in h.said), h.said)
        self.assertEqual(h.clock.now(), rang_at + timedelta(seconds=60))
        self.assertEqual(h.rings, 2)

    def test_snooze_wait_follows_wall_clock_steps(self):
        # Snooze sets a wall-clock target like any alarm: a forward step during the
        # snooze wait makes it ring at once instead of waiting out the full minute.
        h = Harness(["s", "d"], clock=FakeClock(wall_steps={1: 600}),
                    snooze=timedelta(seconds=60))
        self.assertIs(h.run(START), Outcome.DISMISSED)
        self.assertEqual(h.rings, 2)
        self.assertEqual(h.clock.sleeps, [1.0])  # one tick, not 60


class FormatDuration(unittest.TestCase):
    def test_format(self):
        self.assertEqual(format_duration(timedelta(seconds=3725)), "1h 2m 5s")
        self.assertEqual(format_duration(timedelta(minutes=5)), "5m")
        self.assertEqual(format_duration(timedelta(0)), "0s")


if __name__ == "__main__":
    unittest.main()
