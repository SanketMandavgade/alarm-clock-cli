"""Real-process tests: run `python -m alarm_clock` and check signals, stdin, exit codes.

They take a few seconds of real time (alarms are as short as 1s). To stay silent
and portable they run the child with an empty PATH so no native audio player can
be found: only the terminal bell is emitted, into a pipe. Skipped on Windows,
where POSIX signal semantics and `winsound` differ.
"""
import os
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipIf(sys.platform == "win32", "POSIX signals / winsound")
class ProcessTests(unittest.TestCase):
    def start(self, *args):
        empty_path = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, empty_path)
        proc = subprocess.Popen(
            [sys.executable, "-m", "alarm_clock", *args], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, env=dict(os.environ, PATH=empty_path),
        )
        self.addCleanup(self._reap, proc)
        # Blocks until the child has printed its first line: no sleeping needed.
        self.assertIn("Alarm set for", proc.stdout.readline())
        return proc

    @staticmethod
    def _reap(proc):
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()

    def wait_until_ringing(self, proc):
        line = proc.stdout.readline()
        self.assertTrue(line.startswith("Alarm!"), line)

    def finish(self, proc):
        out, err = proc.communicate(timeout=20)
        return proc.returncode, out, err

    def test_sigterm_while_waiting(self):
        proc = self.start("1h")
        proc.send_signal(signal.SIGTERM)
        code, out, err = self.finish(proc)
        self.assertEqual((code, err), (130, ""))
        self.assertIn("Alarm cancelled.", out)

    def test_sigint_while_waiting(self):
        proc = self.start("1h")
        proc.send_signal(signal.SIGINT)
        code, out, err = self.finish(proc)
        self.assertEqual((code, err), (130, ""))
        self.assertIn("Alarm cancelled.", out)

    def test_sigterm_while_ringing_with_stdin_still_open(self):
        proc = self.start("1s")
        self.wait_until_ringing(proc)
        proc.send_signal(signal.SIGTERM)
        code, out, err = self.finish(proc)
        # empty stderr also shows no stdin-reader-thread warning at interpreter exit
        self.assertEqual((code, err), (130, ""))
        self.assertIn("Alarm cancelled.", out)

    def test_dismiss_via_stdin(self):
        proc = self.start("1s")
        self.wait_until_ringing(proc)
        proc.stdin.write("d\n")
        proc.stdin.flush()
        code, _, err = self.finish(proc)
        self.assertEqual((code, err), (0, ""))

    def test_eof_on_stdin_rings_until_max_ring_then_exits_3(self):
        proc = self.start("1s", "--max-ring", "1")
        code, out, err = self.finish(proc)  # communicate() closes stdin => EOF for the child
        self.assertEqual((code, err), (3, ""))
        self.assertIn("timed out", out)

    def test_invalid_time_exits_2_with_message(self):
        proc = subprocess.run([sys.executable, "-m", "alarm_clock", "25:00"], cwd=ROOT,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=20)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error:", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
