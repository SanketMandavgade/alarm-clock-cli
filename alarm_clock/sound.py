"""Best-effort audible alert. Always falls back to the terminal bell."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import List, Optional


def _player_command() -> Optional[List[str]]:
    if sys.platform == "darwin":
        sound = "/System/Library/Sounds/Glass.aiff"
        if shutil.which("afplay") and os.path.exists(sound):
            return ["afplay", sound]
    elif sys.platform.startswith("linux"):
        sound = "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"
        if shutil.which("paplay") and os.path.exists(sound):
            return ["paplay", sound]
        if shutil.which("canberra-gtk-play"):
            return ["canberra-gtk-play", "-i", "alarm-clock-elapsed"]
    return None


class Ringer:
    """Callable that makes one 'ring'. Call close() to stop any playing sound.

    ``command`` overrides player discovery (used by tests; ``[]`` means bell only); ``stop_timeout`` is
    how long close() waits after terminate() before escalating to kill().
    """

    def __init__(self, command: Optional[List[str]] = None, stop_timeout: float = 1.0) -> None:
        self._command = command if command is not None else _player_command()
        self._stop_timeout = stop_timeout
        self._proc: Optional[subprocess.Popen] = None

    def __call__(self) -> None:
        sys.stdout.write("\a")
        sys.stdout.flush()
        if sys.platform == "win32":
            try:
                import winsound

                winsound.Beep(880, 300)
            except (ImportError, RuntimeError):
                pass
            return
        if not self._command:
            return
        if self._proc is not None and self._proc.poll() is None:
            return  # previous sound still playing; don't overlap
        try:
            self._proc = subprocess.Popen(
                self._command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self._command = None  # player vanished; bell only from now on

    def close(self) -> None:
        """Stop any playing sound. Bounded (~2x stop_timeout) and never raises.

        Runs from ``finally`` blocks, so it must not mask the original exception.
        """
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=self._stop_timeout)
            except subprocess.TimeoutExpired:
                proc.kill()  # player ignored SIGTERM
                proc.wait(timeout=self._stop_timeout)
        except (OSError, subprocess.TimeoutExpired):
            pass  # already gone, or unkillable; nothing more we can do
