"""Signal handling for clean cancellation in the synchronous CLI.

Installs SIGINT/SIGTERM handlers that set a :class:`threading.Event` instead of
raising, so in-flight work can finish the current item, flush completed batches,
release locks, and close descriptors before exiting -- without dumping a
traceback during ordinary Ctrl+C.
"""

from __future__ import annotations

import signal
import threading
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def cancellation_scope() -> Iterator[threading.Event]:
    """Yield an Event set on SIGINT/SIGTERM; restores prior handlers on exit."""
    cancel = threading.Event()
    previous: dict[int, object] = {}

    def _handler(signum, _frame):  # noqa: ANN001 - signal handler signature
        cancel.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[sig] = signal.getsignal(sig)
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            # Not on the main thread, or signal unavailable; skip gracefully.
            pass

    try:
        yield cancel
    finally:
        for sig, handler in previous.items():
            try:
                signal.signal(sig, handler)  # type: ignore[arg-type]
            except (ValueError, OSError):
                pass
