"""Discord webhook notifications: fire-and-forget, never blocks the caller."""

from __future__ import annotations

import threading
import time
import traceback
from collections import deque

import requests

from logger import get_logger
from utils import VideoInfo, human_size, utc_now_iso

COLOR_INFO = 0x3498DB
COLOR_SUCCESS = 0x2ECC71
COLOR_WARNING = 0xF39C12
COLOR_ERROR = 0xE74C3C

_MAX_QUEUE = 200
_POLL_IDLE_SECONDS = 0.5
_MAX_BACKOFF_SECONDS = 300
_STACK_TRACE_LIMIT = 800

logger = get_logger(__name__)


class Notifier:
    def __init__(self, webhook_url: str, enabled: bool) -> None:
        self.webhook_url = webhook_url
        self.enabled = enabled
        self._queue: deque[tuple[dict, int]] = deque(maxlen=_MAX_QUEUE)
        self._shutdown_event = threading.Event()
        self._thread: threading.Thread | None = None
        if self.enabled:
            self._thread = threading.Thread(
                target=self._worker, name="notifier-worker", daemon=True
            )
            self._thread.start()

    def send(
        self,
        title: str,
        description: str = "",
        color: int = COLOR_INFO,
        fields: list[dict] | None = None,
        thumbnail_url: str | None = None,
    ) -> None:
        logger.info("DISCORD: %s — %s", title, description)
        if not self.enabled:
            return
        payload: dict = {
            "title": title,
            "description": description,
            "color": color,
            "fields": fields or [],
            "timestamp": utc_now_iso(),
        }
        if thumbnail_url:
            payload["thumbnail"] = {"url": thumbnail_url}
        self._queue.append((payload, 0))

    def error(
        self,
        exc: BaseException,
        module: str,
        current_task: str,
        retry_count: int = 0,
    ) -> None:
        tb = traceback.extract_tb(exc.__traceback__)
        line_no = tb[-1].lineno if tb else None
        stack = traceback.format_exc()[-_STACK_TRACE_LIMIT:]
        fields = [
            {"name": "Type", "value": type(exc).__name__, "inline": True},
            {"name": "Module", "value": module, "inline": True},
            {"name": "Line", "value": str(line_no), "inline": True},
            {"name": "Task", "value": current_task, "inline": False},
            {"name": "Retry Count", "value": str(retry_count), "inline": True},
            {"name": "Stack Trace", "value": f"```{stack}```", "inline": False},
        ]
        self.send(
            title=f"Error in {module}",
            description=str(exc)[:500],
            color=COLOR_ERROR,
            fields=fields,
        )

    def upload_success(
        self,
        video: VideoInfo,
        uploaded_id: str,
        channel_name: str,
        file_size: int,
        upload_time_iso: str,
    ) -> None:
        fields = [
            {"name": "Source", "value": f"https://youtu.be/{video.video_id}", "inline": True},
            {"name": "Destination", "value": f"https://youtu.be/{uploaded_id}", "inline": True},
            {"name": "Channel", "value": channel_name, "inline": True},
            {"name": "Source Channel", "value": video.source_channel_name or "unknown", "inline": True},
            {"name": "Duration", "value": f"{video.duration_seconds}s", "inline": True},
            {"name": "Size", "value": human_size(file_size), "inline": True},
            {"name": "Uploaded At", "value": upload_time_iso, "inline": True},
        ]
        self.send(
            title=video.title,
            description="Uploaded successfully",
            color=COLOR_SUCCESS,
            fields=fields,
            thumbnail_url=video.thumbnail_url,
        )

    def shutdown(self, timeout: float = 5.0) -> None:
        if self._thread is None:
            return
        deadline = time.monotonic() + timeout
        while self._queue and time.monotonic() < deadline:
            time.sleep(0.1)
        self._shutdown_event.set()
        self._thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def _worker(self) -> None:
        while not self._shutdown_event.is_set():
            if not self._queue:
                self._shutdown_event.wait(_POLL_IDLE_SECONDS)
                continue
            payload, attempt = self._queue.popleft()
            try:
                response = requests.post(
                    self.webhook_url, json={"embeds": [payload]}, timeout=10
                )
                if response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", 5))
                    self._queue.appendleft((payload, attempt))
                    self._shutdown_event.wait(retry_after)
                    continue
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001 - must never kill the thread
                self._queue.appendleft((payload, attempt + 1))
                logger.warning("Discord webhook post failed (attempt %d): %s", attempt + 1, exc)
                self._shutdown_event.wait(min(2**attempt, _MAX_BACKOFF_SECONDS))


def _demo() -> None:
    n = Notifier(webhook_url="http://example.invalid/webhook", enabled=False)
    n.send("Test", "hello")
    assert len(n._queue) == 0  # disabled -> never queues

    n2 = Notifier(webhook_url="http://example.invalid/webhook", enabled=True)
    n2.send("Test", "hello")
    assert len(n2._queue) == 1
    try:
        raise ValueError("boom")
    except ValueError as exc:
        n2.error(exc, module="notifier", current_task="demo", retry_count=1)
    assert len(n2._queue) == 2
    n2.shutdown(timeout=0.2)
    print("notifier self-check OK")


if __name__ == "__main__":
    _demo()
