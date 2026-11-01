import signal
import sys

from .cli import main


def _terminate(signum, frame):
    raise KeyboardInterrupt  # route SIGTERM through the same clean-cancel path


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)
    sys.exit(main())
