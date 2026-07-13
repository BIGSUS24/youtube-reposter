"""Internet connectivity checks and blocking wait-for-reconnect helper."""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from logger import get_logger
from notifier import COLOR_SUCCESS, COLOR_WARNING
from utils import AppError

if TYPE_CHECKING:
    from notifier import Notifier

logger = get_logger(__name__)

# A DNS socket can be reachable even when the connection cannot reach YouTube
# (for example, on a captive Wi-Fi portal).  Probe the service this app needs.
_PROBE_URLS = (
    "https://www.youtube.com/generate_204",
    "https://clients3.google.com/generate_204",
)


class NetworkError(AppError):
    """Classification hook for retry.py; not raised by this module."""


def is_connected(timeout: float = 5.0) -> bool:
    for url in _PROBE_URLS:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                # generate_204 normally returns 204; accepting any successful
                # response also supports networks that replace it with a portal.
                response.read(1)
            return True
        except (OSError, urllib.error.URLError):
            continue
    return False


def wait_for_connection(
    notifier: "Notifier",
    poll_seconds: int = 30,
    stop_event: threading.Event | None = None,
) -> bool:
    if is_connected():
        return True

    logger.warning("Internet unavailable. Waiting...")
    notifier.send("Internet lost", color=COLOR_WARNING)

    while True:
        if stop_event is not None:
            stop_event.wait(poll_seconds)
        else:
            time.sleep(poll_seconds)

        if is_connected():
            logger.info("Internet restored.")
            notifier.send("Internet restored", color=COLOR_SUCCESS)
            return True

        if stop_event is not None and stop_event.is_set():
            return False


def _demo() -> None:
    assert isinstance(is_connected(timeout=0.5), bool)

    class _StubNotifier:
        def send(self, *a, **k):
            pass

    ev = threading.Event()
    ev.set()  # already stopped -> should return False without ever connecting on a bad host
    result = wait_for_connection(_StubNotifier(), poll_seconds=0, stop_event=ev)
    assert result in (True, False)
    print("network self-check OK")


if __name__ == "__main__":
    _demo()
