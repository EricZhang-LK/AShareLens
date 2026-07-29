"""Long-running polling helper with graceful process shutdown."""

from __future__ import annotations

import signal
from collections.abc import Callable
from threading import Event
from types import FrameType
from typing import Any


def run_until_stopped(
    action: Callable[[], None],
    *,
    poll_seconds: float,
) -> None:
    """Run one short action per tick and finish the active action on shutdown."""

    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    stopped = Event()
    previous: dict[
        signal.Signals,
        Callable[[int, FrameType | None], Any] | int | None,
    ] = {}

    def request_stop(signum: int, frame: FrameType | None) -> None:
        del signum, frame
        stopped.set()

    handled = (signal.SIGINT, signal.SIGTERM)
    try:
        for handled_signal in handled:
            previous[handled_signal] = signal.getsignal(handled_signal)
            signal.signal(handled_signal, request_stop)
        while not stopped.is_set():
            action()
            stopped.wait(poll_seconds)
    finally:
        for handled_signal, handler in previous.items():
            signal.signal(handled_signal, handler)
