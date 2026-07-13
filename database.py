"""SQLite (WAL) store of uploaded videos, with corruption recovery."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import utils
from logger import get_logger
from notifier import Notifier

log = get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS uploaded_videos (
    video_id          TEXT PRIMARY KEY,
    upload_date       TEXT NOT NULL,
    uploaded_video_id TEXT NOT NULL,
    title             TEXT NOT NULL
);
"""


class DatabaseCorruptionError(utils.AppError):
    pass


class Database:
    def __init__(self, path: Path, notifier: Notifier) -> None:
        self._path = path
        self._notifier = notifier
        try:
            self._connect()
            healthy = self.verify_integrity()
        except sqlite3.DatabaseError:
            healthy = False
        if not healthy:
            self._recover()

    def _connect(self) -> None:
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def verify_integrity(self) -> bool:
        try:
            row = self._conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError:
            return False
        return bool(row) and row[0] == "ok"

    def _recover(self) -> None:
        """Quarantine the corrupt file, rebuild fresh, notify. Never raises."""
        try:
            log.error("DB integrity check failed; recovering %s", self._path)
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            corrupt = self._path.with_name(f"{self._path.name}.corrupt.{int(time.time())}")
            try:
                self._path.rename(corrupt)
            except OSError as exc:
                log.error("Could not quarantine corrupt DB: %s", exc)
            self._connect()
            self._notifier.send(
                "DB corruption detected",
                f"Database was corrupt and has been rebuilt. Old file: {corrupt}",
                color=0xE74C3C,
            )
        except Exception:  # recovery must never propagate
            log.exception("DB recovery failed")

    def is_uploaded(self, video_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM uploaded_videos WHERE video_id = ?", (video_id,)
        ).fetchone()
        return row is not None

    def record_upload(
        self,
        video_id: str,
        uploaded_video_id: str,
        title: str,
        upload_date: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO uploaded_videos "
            "(video_id, upload_date, uploaded_video_id, title) VALUES (?, ?, ?, ?)",
            (video_id, upload_date or utils.utc_now_iso(), uploaded_video_id, title),
        )
        self._conn.commit()

    def uploads_since(self, iso_utc: str) -> list[tuple[str, str, str, str]]:
        return self._conn.execute(
            "SELECT video_id, upload_date, uploaded_video_id, title "
            "FROM uploaded_videos WHERE upload_date >= ? ORDER BY upload_date",
            (iso_utc,),
        ).fetchall()

    def last_upload_date(self) -> str | None:
        row = self._conn.execute(
            "SELECT MAX(upload_date) FROM uploaded_videos"
        ).fetchone()
        return row[0] if row else None

    def db_size_bytes(self) -> int:
        return self._path.stat().st_size if self._path.exists() else 0

    def close(self) -> None:
        self._conn.close()
