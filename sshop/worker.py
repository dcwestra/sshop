"""Run blocking engine calls off the UI thread.

Message handlers must never call engine.* synchronously — a slow okssh
subprocess (SSH connect, tunnel start, remote command) freezes the whole
UI. Wrap the call:

    run_blocking(self, lambda: engine.wake(name), self._on_wake_done)

fn runs in a thread worker; on_done(result) is delivered back on the UI
thread, so it may touch widgets, notify, push screens, etc.
"""

from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")


def run_blocking(screen, fn: Callable[[], T], on_done: Callable[[T], None]) -> None:
    def _work() -> None:
        result = fn()
        screen.app.call_from_thread(on_done, result)

    screen.run_worker(_work, thread=True, exclusive=False)
