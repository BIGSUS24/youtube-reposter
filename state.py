"""Crash-safe application state persisted as JSON."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

import utils
from logger import get_logger

log = get_logger(__name__)


@dataclass
class AppState:
    last_successful_run: str | None = None            # ISO UTC
    current_task: str | None = None                   # "idle" | "checking" | "downloading:<vid>" | "uploading:<vid>"
    current_download: dict | None = None              # {"video_id": str, "bytes_downloaded": int}
    retry_count: int = 0
    clean_shutdown: bool = True


class StateManager:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> AppState:
        """Return persisted state; on missing file or invalid JSON, a fresh AppState. Never raises."""
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return AppState(clean_shutdown=True)

        fields = {f.name for f in dataclasses.fields(AppState)}
        try:
            return AppState(**{k: v for k, v in raw.items() if k in fields})
        except TypeError:
            log.warning("state.json malformed; starting fresh")
            return AppState(clean_shutdown=True)

    def save(self, state: AppState) -> None:
        utils.atomic_write(self._path, json.dumps(dataclasses.asdict(state), indent=2))
