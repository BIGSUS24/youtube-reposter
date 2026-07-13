"""Download source Shorts via yt-dlp with disk-space preflight and cleanup."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

import imageio_ffmpeg
import yt_dlp

from logger import get_logger
from notifier import Notifier
import notifier as notifier_mod
from utils import (AppError, InsufficientDiskSpaceError, VideoInfo,
                   check_disk_space, human_size)

log = get_logger(__name__)


class DownloadError(AppError):
    """A download failed after retries."""


class Downloader:
    def __init__(self, download_folder: Path, notifier: Notifier,
                 retry: Callable) -> None:
        self._folder = download_folder
        self._notifier = notifier
        self._retry = retry
        self._last_milestone = -1
        self._folder.mkdir(parents=True, exist_ok=True)

    def download(self, video: VideoInfo) -> Path:
        try:
            check_disk_space(self._folder, 500)
        except InsufficientDiskSpaceError as exc:
            self._notifier.send("Disk space low", str(exc),
                                color=notifier_mod.COLOR_ERROR)
            raise

        self._clear_partials(video.video_id)
        self._notifier.send("Download started", video.title)
        self._last_milestone = -1

        url = f"https://www.youtube.com/watch?v={video.video_id}"
        ffmpeg_path = self._ffmpeg_path()
        node_path = shutil.which("node")
        if ffmpeg_path is not None:
            download_format = "bestvideo*+bestaudio/best"
        else:
            download_format = "best[ext=mp4][height<=1080]/best[height<=1080]/best"
            log.warning("ffmpeg not found; falling back to a single-file download format")
            self._notifier.send(
                "ffmpeg not found",
                "Using single-file download fallback. Install ffmpeg for best quality.",
                color=notifier_mod.COLOR_WARNING,
            )

        opts = {
            "outtmpl": str(self._folder / "%(id)s.%(ext)s"),
            "format": download_format,
            "noprogress": True,
            "progress_hooks": [self._hook],
            "quiet": True,
            "remote_components": ["ejs:github"],
            "retries": 3,
        }
        if ffmpeg_path is not None:
            opts["ffmpeg_location"] = ffmpeg_path
            opts["merge_output_format"] = "webm/mp4"
        if node_path is not None:
            opts["js_runtimes"] = {"node": {"path": node_path}}

        def _run() -> None:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

        try:
            self._retry(_run)()
        except (yt_dlp.utils.DownloadError, OSError) as exc:
            self._notifier.send("Download failed", str(exc),
                                color=notifier_mod.COLOR_ERROR)
            raise DownloadError(str(exc)) from exc

        path = self._locate(video.video_id)
        size = path.stat().st_size
        self._notifier.send("Download completed", human_size(size),
                            color=notifier_mod.COLOR_SUCCESS)
        return path

    def _ffmpeg_path(self) -> str | None:
        """Return system ffmpeg or the Python-packaged ffmpeg binary."""
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            return system_ffmpeg
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:  # noqa: BLE001 - fallback remains valid
            log.warning("imageio-ffmpeg unavailable: %s", exc)
            return None

    def cleanup(self, video_id: str | None = None) -> None:
        if video_id is not None:
            targets = self._folder.glob(f"{video_id}*")
        else:
            targets = (p for p in self._folder.iterdir() if p.is_file())
        for target in targets:
            try:
                target.unlink()
            except OSError as exc:
                log.warning("Cleanup failed for %s: %s", target, exc)

    def _clear_partials(self, video_id: str) -> None:
        for pattern in (f"{video_id}*.part", f"{video_id}*.ytdl"):
            for partial in self._folder.glob(pattern):
                try:
                    partial.unlink()
                    log.info("Removed stale partial %s", partial)
                except OSError as exc:
                    log.warning("Could not remove partial %s: %s", partial, exc)

    def _locate(self, video_id: str) -> Path:
        expected = self._folder / f"{video_id}.mp4"
        if expected.exists():
            return expected
        for candidate in self._folder.glob(f"{video_id}.*"):
            if candidate.suffix not in (".part", ".ytdl"):
                return candidate
        raise DownloadError(f"Downloaded file for {video_id} not found")

    def _hook(self, d: dict) -> None:
        if d.get("status") != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        done = d.get("downloaded_bytes")
        if not total or done is None:
            return
        pct = int(done / total * 100)
        milestone = pct - (pct % 25)
        if milestone > self._last_milestone and milestone in (0, 25, 50, 75, 100):
            self._last_milestone = milestone
            log.info("Download progress: %d%%", milestone)
