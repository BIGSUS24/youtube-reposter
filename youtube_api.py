"""YouTube Data API v3 client: auth, latest-Short discovery, and upload."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

import google.auth.transport.requests
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
import googleapiclient.http

import utils
from logger import get_logger
from notifier import Notifier
from utils import AppError, VideoInfo

log = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]

_QUOTA_REASONS = {"quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded"}
_DURATION_RE = re.compile(
    r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
)


class YouTubeAPIError(AppError):
    """Any non-quota YouTube API failure."""


class QuotaExceededError(YouTubeAPIError):
    """Daily quota / rate limit hit -- must not be retried (resets daily)."""


class AuthError(YouTubeAPIError):
    """OAuth refresh failed or client json invalid."""


def _parse_duration(iso: str) -> int:
    """PT#H#M#S ISO-8601 duration -> total seconds (isodate not available)."""
    match = _DURATION_RE.fullmatch(iso or "")
    if not match:
        return 0
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _http_reason(exc: googleapiclient.errors.HttpError) -> str:
    """Best-effort extraction of the API error reason string from an HttpError."""
    details = getattr(exc, "error_details", None)
    if details:
        for item in details:
            reason = item.get("reason") if isinstance(item, dict) else None
            if reason:
                return reason
    try:
        payload = json.loads(exc.content.decode("utf-8"))
        errors = payload.get("error", {}).get("errors", [])
        if errors and errors[0].get("reason"):
            return errors[0]["reason"]
    except (ValueError, AttributeError, KeyError, TypeError):
        pass
    return ""


def _classify(exc: googleapiclient.errors.HttpError) -> YouTubeAPIError:
    """Map an HttpError to QuotaExceededError or plain YouTubeAPIError."""
    if _http_reason(exc) in _QUOTA_REASONS:
        return QuotaExceededError(str(exc))
    return YouTubeAPIError(str(exc))


class YouTubeClient:
    def __init__(self, oauth_client_json: Path, token_json: Path,
                 notifier: Notifier, retry: Callable) -> None:
        self._oauth_client_json = oauth_client_json
        self._token_json = token_json
        self._notifier = notifier
        self._retry = retry
        self._yt: googleapiclient.discovery.Resource | None = None
        self._channel_title: str | None = None

    def authenticate(self) -> None:
        try:
            if self._token_json.exists():
                creds = google.oauth2.credentials.Credentials.from_authorized_user_file(
                    str(self._token_json), SCOPES)
                if creds.expired and creds.refresh_token:
                    creds.refresh(google.auth.transport.requests.Request())
                    self._notifier.send("Token refreshed successfully")
                    utils.atomic_write(self._token_json, creds.to_json())
            else:
                flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                    str(self._oauth_client_json), SCOPES)
                creds = self._run_oauth_flow(flow)
                self._token_json.parent.mkdir(parents=True, exist_ok=True)
                utils.atomic_write(self._token_json, creds.to_json())
        except Exception as exc:  # noqa: BLE001 -- any auth/refresh failure is fatal
            raise AuthError(str(exc)) from exc

        self._yt = googleapiclient.discovery.build(
            "youtube", "v3", credentials=creds, cache_discovery=False)

    def _run_oauth_flow(
        self, flow: google_auth_oauthlib.flow.InstalledAppFlow
    ) -> google.oauth2.credentials.Credentials:
        """Run the installed-app OAuth flow.

        Recent google-auth-oauthlib releases removed run_console(). The supported
        replacement is a loopback local server flow, which prints the auth URL
        and waits for Google's redirect after the user approves access.
        """
        return flow.run_local_server(
            host="127.0.0.1",
            port=0,
            authorization_prompt_message=(
                "Open this URL in your browser to authorize the app:\n{url}\n"
            ),
            success_message="Authentication complete. You can close this window.",
            open_browser=False,
        )

    def token_valid(self) -> bool:
        """True once authenticate() has built the client this run (self-test only)."""
        return self._yt is not None

    def get_latest_short(self, channel_id: str) -> VideoInfo | None:
        shorts = self.get_recent_shorts(channel_id, max_results=5)
        return shorts[0] if shorts else None

    def get_recent_shorts(
        self, channel_id: str, max_results: int = 5
    ) -> list[VideoInfo]:
        return self._retry(self._get_recent_shorts)(channel_id, max_results)

    def _get_recent_shorts(
        self, channel_id: str, max_results: int = 5
    ) -> list[VideoInfo]:
        try:
            channels = self._yt.channels().list(
                part="contentDetails", id=channel_id).execute()
            items = channels.get("items", [])
            if not items:
                return []
            uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

            playlist = self._yt.playlistItems().list(
                part="snippet,contentDetails", playlistId=uploads,
                maxResults=max(1, min(max_results, 50))).execute()
            video_ids = [i["contentDetails"]["videoId"]
                         for i in playlist.get("items", [])]
            if not video_ids:
                return []

            videos = self._yt.videos().list(
                part="contentDetails,snippet",
                id=",".join(video_ids)).execute()

            candidates = sorted(
                videos.get("items", []),
                key=lambda v: v["snippet"]["publishedAt"],
                reverse=True)
            shorts: list[VideoInfo] = []
            for video in candidates:
                duration = _parse_duration(
                    video["contentDetails"].get("duration", ""))
                if duration <= 61:
                    snippet = video["snippet"]
                    thumbs = snippet.get("thumbnails", {})
                    thumb = (thumbs.get("high") or thumbs.get("medium")
                             or thumbs.get("default") or {})
                    shorts.append(VideoInfo(
                        video_id=video["id"],
                        title=snippet.get("title", ""),
                        description=snippet.get("description", ""),
                        duration_seconds=duration,
                        published_at=snippet["publishedAt"],
                        thumbnail_url=thumb.get("url", ""),
                        source_channel_id=channel_id,
                    ))
            return shorts
        except googleapiclient.errors.HttpError as exc:
            raise _classify(exc) from exc

    def find_existing_upload(self, title: str) -> str | None:
        try:
            channels = self._yt.channels().list(
                part="contentDetails", mine=True).execute()
            items = channels.get("items", [])
            if not items:
                return None
            uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
            playlist = self._yt.playlistItems().list(
                part="snippet,contentDetails", playlistId=uploads,
                maxResults=10).execute()
            for item in playlist.get("items", []):
                if item["snippet"].get("title") == title:
                    return item["contentDetails"]["videoId"]
            return None
        except googleapiclient.errors.HttpError as exc:
            raise _classify(exc) from exc

    def upload_video(self, file_path: Path, title: str, description: str) -> str:
        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }
        media = googleapiclient.http.MediaFileUpload(
            str(file_path), chunksize=1024 * 1024, resumable=True)
        try:
            request = self._yt.videos().insert(
                part="snippet,status", body=body, media_body=media)
            response = None
            last_logged = -1
            while response is None:
                status, response = request.next_chunk()
                if status is not None:
                    pct = int(status.progress() * 100)
                    if pct >= last_logged + 25:
                        last_logged = pct - (pct % 25)
                        log.info("Upload progress: %d%%", pct)
            return response["id"]
        except googleapiclient.errors.HttpError as exc:
            raise _classify(exc) from exc

    def channel_title(self) -> str:
        if self._channel_title is None:
            try:
                channels = self._yt.channels().list(
                    part="snippet", mine=True).execute()
            except googleapiclient.errors.HttpError as exc:
                raise _classify(exc) from exc
            self._channel_title = channels["items"][0]["snippet"]["title"]
        return self._channel_title
