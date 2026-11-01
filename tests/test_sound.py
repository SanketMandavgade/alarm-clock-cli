import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

from alarm_clock import sound
from alarm_clock.sound import Ringer


class FakeProc:
    def __init__(self, ignores_terminate=False, terminate_error=None):
        self.alive = True
        self.terminated = self.killed = False
        self._ignores = ignores_terminate
        self._terminate_error = terminate_error

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.terminated = True
        if self._terminate_error:
            raise self._terminate_error
        if not self._ignores:
            self.alive = False

    def kill(self):
        self.killed = True
        self.alive = False

    def wait(self, timeout=None):
        if self.alive:
            raise subprocess.TimeoutExpired("player", timeout)
        return 0


def ringer_with(proc):
    r = Ringer(command=["player"])
    r._proc = proc
    return r


class CloseTests(unittest.TestCase):
    def test_terminates_running_player_without_kill(self):
        proc = FakeProc()
        ringer_with(proc).close()
        self.assertTrue(proc.terminated)
        self.assertFalse(proc.killed)
        self.assertFalse(proc.alive)

    def test_kills_player_that_ignores_terminate(self):
        proc = FakeProc(ignores_terminate=True)
        ringer_with(proc).close()
        self.assertTrue(proc.killed)
        self.assertFalse(proc.alive)

    def test_already_exited_player_is_left_alone(self):
        proc = FakeProc()
        proc.alive = False
        ringer_with(proc).close()
        self.assertFalse(proc.terminated)

    def test_close_never_raises(self):
        # close() runs in finally blocks and must not mask the original exception.
        ringer_with(FakeProc(terminate_error=ProcessLookupError())).close()
        ringer_with(FakeProc(terminate_error=PermissionError())).close()

    def test_close_without_player_or_twice_is_harmless(self):
        r = Ringer(command=["player"])
        r.close()
        r._proc = FakeProc()
        r.close()
        r.close()

    @unittest.skipIf(sys.platform == "win32", "uses a POSIX-style child process")
    def test_real_child_that_ignores_sigterm_is_gone_after_close(self):
        code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
        proc = subprocess.Popen([sys.executable, "-c", code])
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        ringer = ringer_with(proc)
        ringer._stop_timeout = 0.2
        ringer.close()
        self.assertIsNotNone(proc.poll(), "player process was left running")


@unittest.skipIf(sys.platform == "win32", "Windows rings via winsound, not a subprocess")
class RingTests(unittest.TestCase):
    def ring(self, ringer):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ringer()
        return buf.getvalue()

    def test_always_emits_terminal_bell_even_without_player(self):
        with mock.patch.object(sound.subprocess, "Popen") as popen:
            self.assertEqual(self.ring(Ringer(command=[])), "\a")
            popen.assert_not_called()

    def test_does_not_overlap_sounds_and_restarts_after_exit(self):
        first, second = FakeProc(), FakeProc()
        with mock.patch.object(sound.subprocess, "Popen", side_effect=[first, second]) as popen:
            r = Ringer(command=["player"])
            self.ring(r)
            self.ring(r)                 # first still playing -> no new process
            self.assertEqual(popen.call_count, 1)
            first.alive = False
            self.ring(r)                 # first finished -> play again
            self.assertEqual(popen.call_count, 2)

    def test_missing_player_falls_back_to_bell_only(self):
        with mock.patch.object(sound.subprocess, "Popen", side_effect=FileNotFoundError) as popen:
            r = Ringer(command=["gone"])
            self.assertEqual(self.ring(r), "\a")
            self.assertEqual(self.ring(r), "\a")
            self.assertEqual(popen.call_count, 1)  # stops trying after the first failure


if __name__ == "__main__":
    unittest.main()
