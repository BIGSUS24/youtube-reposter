"""Runs cycle_fn on a fixed interval forever; SIGTERM/SIGINT-responsive via stop_event."""

from __future__ import annotations

import threading
import time
from typing import Callable

import network
from logger import get_logger

logger = get_logger(__name__)

_DAY_SECONDS = 24 * 60 * 60
_NETWORK_POLL_SECONDS = 10


class Scheduler:
    def __init__(
        self,
        cycle_fn: Callable[[], None],
        interval_minutes: int,
        notifier,
        stop_event: threading.Event,
        heartbeat_fn: Callable[[], None] | None = None,
        summary_fn: Callable[[], None] | None = None,
    ) -> None:
        self.cycle_fn = cycle_fn
        self.interval_minutes = interval_minutes
        self.notifier = notifier
        self.stop_event = stop_event
        self.heartbeat_fn = heartbeat_fn
        self.summary_fn = summary_fn
        self._last_heartbeat = time.monotonic()
        self._last_summary = time.monotonic()

    def run_forever(self) -> None:
        while not self.stop_event.is_set():
            if not network.wait_for_connection(
                self.notifier, _NETWORK_POLL_SECONDS, self.stop_event
            ):
                break  # stop_event was set while waiting for connectivity

            try:
                self.cycle_fn()
            except Exception as exc:  # noqa: BLE001 - the scheduler loop must never die
                logger.error("Cycle failed: %s", exc, exc_info=True)
                self.notifier.error(exc, "scheduler", "cycle")

            now = time.monotonic()
            if self.summary_fn is not None and now - self._last_summary >= _DAY_SECONDS:
                self._last_summary = now
                try:
                    self.summary_fn()
                except Exception as exc:  # noqa: BLE001
                    logger.error("Daily summary failed: %s", exc, exc_info=True)
                    self.notifier.error(exc, "scheduler", "summary")

            if self.heartbeat_fn is not None and now - self._last_heartbeat >= _DAY_SECONDS:
                self._last_heartbeat = now
                try:
                    self.heartbeat_fn()
                except Exception as exc:  # noqa: BLE001
                    logger.error("Heartbeat failed: %s", exc, exc_info=True)
                    self.notifier.error(exc, "scheduler", "heartbeat")

            next_run = time.monotonic() + self.interval_minutes * 60
            # Detect a Wi-Fi outage even while idling.  As soon as it returns,
            # leave the normal interval early and run a fresh cycle.
            connection_restored = False
            while time.monotonic() < next_run and not self.stop_event.is_set():
                if not network.is_connected(timeout=3):
                    if not network.wait_for_connection(
                        self.notifier, _NETWORK_POLL_SECONDS, self.stop_event
                    ):
                        return
                    connection_restored = True
                    break
                self.stop_event.wait(_NETWORK_POLL_SECONDS)

            if connection_restored:
                logger.info("Connection restored; checking for new Shorts immediately")


def _demo() -> None:
    calls = {"cycles": 0}
    stop_event = threading.Event()

    # Stub out network I/O so the self-check is deterministic offline.
    network.wait_for_connection = lambda notifier, poll_seconds=30, stop_event=None: True
    network.is_connected = lambda timeout=5.0: True

    def cycle() -> None:
        calls["cycles"] += 1
        stop_event.set()

    class _StubNotifier:
        def error(self, *a, **k):
            pass

    sched = Scheduler(cycle, interval_minutes=0, notifier=_StubNotifier(), stop_event=stop_event)
    sched.run_forever()
    assert calls["cycles"] == 1
    print("scheduler self-check OK")


if __name__ == "__main__":
    _demo()
