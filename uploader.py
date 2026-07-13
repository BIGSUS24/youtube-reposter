"""Upload downloaded Shorts to the destination channel, crash-safe and dedup-aware."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import notifier as notifier_mod
from database import Database
from logger import get_logger
from notifier import Notifier
from state import AppState, StateManager
from utils import AppError, VideoInfo, utc_now_iso
from youtube_api import QuotaExceededError, YouTubeAPIError, YouTubeClient

log = get_logger("upload")


class UploadError(AppError):
    """Upload failed after retries (non-quota)."""


class DuplicateUploadError(AppError):
    """Video already uploaded -- caller treats as success no-op."""


class Uploader:
    def __init__(self, client: YouTubeClient, db: Database,
                 state_mgr: StateManager, state: AppState,
                 notifier: Notifier, retry: Callable) -> None:
        self._client = client
        self._db = db
        self._state_mgr = state_mgr
        self._state = state
        self._notifier = notifier
        self._retry = retry

    def upload(self, file_path: Path, video: VideoInfo) -> str:
        if self._db.is_uploaded(video.video_id):
            self._notifier.send("Duplicate detected", video.title,
                                color=notifier_mod.COLOR_WARNING)
            raise DuplicateUploadError(video.video_id)

        # Recover from a crash mid-upload on the previous run.
        if self._state.current_task == f"uploading:{video.video_id}":
            existing = self._client.find_existing_upload(video.title)
            if existing:
                log.info("Recovered prior upload %s for %s",
                         existing, video.video_id)
                self._db.record_upload(video.video_id, existing, video.title)
                return existing

        self._state.current_task = f"uploading:{video.video_id}"
        self._state_mgr.save(self._state)

        self._notifier.send("Upload started", video.title)
        try:
            uploaded_id = self._retry(self._client.upload_video)(
                file_path, video.title, video.description)
        except QuotaExceededError:
            # Expected: scheduler logs/notifies and skips the cycle. Leave
            # current_task as "uploading:<vid>" so the next run resolves it.
            raise
        except (YouTubeAPIError, ConnectionError, TimeoutError) as exc:
            # Exhausted non-quota retries. Leave current_task unchanged so
            # step 2 recovers a possibly-completed upload on the next run.
            self._notifier.send("Upload failed", str(exc),
                                color=notifier_mod.COLOR_ERROR)
            raise UploadError(str(exc)) from exc

        self._db.record_upload(video.video_id, uploaded_id, video.title)
        file_size = file_path.stat().st_size
        self._notifier.upload_success(
            video, uploaded_id, self._client.channel_title(),
            file_size, utc_now_iso())

        self._state.current_task = "idle"
        self._state_mgr.save(self._state)
        return uploaded_id
