"""Integration glue: wires all components together and runs the scheduler forever."""

from __future__ import annotations

import signal
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import database
import downloader
import logger as logging_setup
import network
import notifier as notifier_mod
import retry as retry_mod
import scheduler as scheduler_mod
import state as state_mod
import uploader
import utils
import youtube_api

log = logging_setup.get_logger(__name__)


def _resolve(base: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (base / p)


def _source_label(source: dict) -> str:
    return source.get("name") or source["channel_id"]


def _source_fetch_limit(config: dict) -> int:
    value = int(config.get("max_shorts_per_channel_per_cycle", 1))
    return max(1, min(value, 5))


def build_app(
    config_path: Path = Path("config.yaml"), *, authenticate: bool = True
) -> dict:
    config = utils.load_config(config_path)
    base = config_path.parent.resolve()

    config["download_folder"] = _resolve(base, config["download_folder"]).resolve()
    config["database"] = _resolve(base, config["database"]).resolve()
    config["log_folder"] = _resolve(base, config["log_folder"]).resolve()
    config["destination_channel"]["oauth_client_json"] = _resolve(
        base, config["destination_channel"]["oauth_client_json"]
    ).resolve()
    config["destination_channel"]["token_json"] = _resolve(
        base, config["destination_channel"]["token_json"]
    ).resolve()

    logging_setup.setup_logging(config["log_folder"])

    notifier = notifier_mod.Notifier(config["discord"]["webhook_url"], config["discord"]["enabled"])

    state_path = config["database"].parent / "state.json"
    state_mgr = state_mod.StateManager(state_path)
    state = state_mgr.load()

    db = database.Database(config["database"], notifier)

    retry = retry_mod.build_retry(
        config["max_retry_attempts"], config["retry_delay_seconds"], notifier,
        exclude=(youtube_api.QuotaExceededError,),
    )

    client = youtube_api.YouTubeClient(
        config["destination_channel"]["oauth_client_json"],
        config["destination_channel"]["token_json"],
        notifier,
        retry,
    )
    if authenticate:
        client.authenticate()

    dl = downloader.Downloader(config["download_folder"], notifier, retry)
    up = uploader.Uploader(client, db, state_mgr, state, notifier, retry)

    return {
        "config": config,
        "notifier": notifier,
        "state_mgr": state_mgr,
        "state": state,
        "db": db,
        "client": client,
        "downloader": dl,
        "uploader": up,
        "retry": retry,
        "start_time": time.monotonic(),
    }


def authenticate_when_online(components: dict, stop_event: threading.Event) -> bool:
    """Wait through an outage, then authenticate without letting startup die.

    Token refresh needs the network.  Keeping this outside ``build_app`` means
    a phone reboot while Wi-Fi is down stays alive until the router returns.
    """
    notifier = components["notifier"]
    client = components["client"]
    while not stop_event.is_set():
        if not network.wait_for_connection(notifier, poll_seconds=10, stop_event=stop_event):
            return False
        try:
            client.authenticate()
            return True
        except youtube_api.AuthError as exc:
            # If the Wi-Fi disappeared between the probe and token refresh,
            # wait again.  Invalid credentials while online are a real setup
            # problem, so surface them instead of retrying forever.
            if not network.is_connected(timeout=3):
                log.warning("Authentication interrupted by network loss: %s", exc)
                continue
            raise
    return False


def self_test(components: dict) -> bool:
    config = components["config"]
    notifier = components["notifier"]
    failures: list[str] = []
    fatal = False

    try:
        utils.check_disk_space(config["download_folder"], 500)
    except Exception as exc:
        failures.append(f"Disk space: {exc}")
        fatal = True

    try:
        if not components["db"].verify_integrity():
            failures.append("Database integrity check failed")
            fatal = True
    except Exception as exc:
        failures.append(f"Database integrity check errored: {exc}")
        fatal = True

    try:
        if not network.is_connected():
            log.warning("No internet connectivity at startup (non-fatal)")
            failures.append("No internet connectivity at startup (non-fatal)")
    except Exception as exc:
        failures.append(f"Network check errored: {exc}")

    try:
        if not components["client"].token_valid():
            failures.append("YouTube auth token invalid")
            fatal = True
    except Exception as exc:
        failures.append(f"Auth check errored: {exc}")
        fatal = True

    if fatal:
        notifier.send(
            "Startup self-test failed",
            "\n".join(failures),
            color=notifier_mod.COLOR_ERROR,
        )
        return False

    notifier.send(
        "Startup self-test passed",
        "\n".join(failures) if failures else "",
        color=notifier_mod.COLOR_SUCCESS,
    )
    return True


def run_cycle(components: dict) -> None:
    config = components["config"]
    client = components["client"]
    db = components["db"]
    notifier = components["notifier"]
    state = components["state"]
    state_mgr = components["state_mgr"]

    per_source_limit = _source_fetch_limit(config)
    candidates: list[utils.VideoInfo] = []
    checked_fields: list[dict] = []

    for source in config["source_channels"]:
        source_name = _source_label(source)
        state.current_task = f"checking:{source_name}"
        state_mgr.save(state)

        videos = client.get_recent_shorts(
            source["channel_id"],
            max_results=max(5, per_source_limit),
        )
        if not videos:
            log.info("No short found for %s", source_name)
            checked_fields.append({"name": source_name, "value": "no shorts"})
            continue

        new_videos: list[utils.VideoInfo] = []
        for video in videos:
            tagged = replace(
                video,
                source_channel_id=source["channel_id"],
                source_channel_name=source_name,
            )
            if db.is_uploaded(tagged.video_id):
                continue
            new_videos.append(tagged)

        selected = new_videos[:per_source_limit]
        candidates.extend(selected)
        status = f"{len(selected)} new" if selected else "no new shorts"
        checked_fields.append({"name": source_name, "value": status})

    if not candidates:
        log.info("No new short found across %d source channel(s)", len(config["source_channels"]))
        notifier.send("No new short found", fields=checked_fields)
        state.last_successful_run = utils.utc_now_iso()
        state.current_task = "idle"
        state.current_download = None
        state.retry_count = 0
        state_mgr.save(state)
        return

    for video in sorted(candidates, key=lambda item: item.published_at):
        if db.is_uploaded(video.video_id):
            log.info("Duplicate detected: %s", video.title)
            notifier.send(
                "Duplicate detected",
                video.title,
                color=notifier_mod.COLOR_WARNING,
                fields=[{"name": "Source Channel", "value": video.source_channel_name or "unknown"}],
            )
            continue

        notifier.send(
            "New short detected",
            video.title,
            fields=[{"name": "Source Channel", "value": video.source_channel_name or "unknown"}],
        )
        state.current_task = f"downloading:{video.video_id}"
        state_mgr.save(state)

        path = components["downloader"].download(video)

        try:
            components["uploader"].upload(path, video)
        except uploader.DuplicateUploadError:
            pass  # already logged/notified inside uploader
        except youtube_api.QuotaExceededError as exc:
            log.warning("Quota exceeded during upload: %s", exc)
            notifier.error(exc, "youtube_api", "uploading")
            return

        if config["delete_download_after_upload"]:
            components["downloader"].cleanup(video.video_id)

    state.last_successful_run = utils.utc_now_iso()
    state.current_task = "idle"
    state.current_download = None
    state.retry_count = 0
    state_mgr.save(state)


def send_heartbeat(components: dict) -> None:
    import psutil

    proc = psutil.Process()
    mem_mb = proc.memory_info().rss / 1024**2
    cpu = proc.cpu_percent(interval=1)

    uptime_seconds = int(time.monotonic() - components["start_time"])
    days, rem = divmod(uptime_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    db = components["db"]
    state = components["state"]
    fields = [
        {"name": "Uptime", "value": f"{days}d {hours}h {minutes}m", "inline": True},
        {"name": "Memory", "value": f"{mem_mb:.1f} MB", "inline": True},
        {"name": "CPU", "value": f"{cpu:.1f}%", "inline": True},
        {"name": "DB size", "value": utils.human_size(db.db_size_bytes()), "inline": True},
        {"name": "Last Upload", "value": db.last_upload_date() or "never", "inline": True},
        {"name": "Last Check", "value": state.last_successful_run or "never", "inline": True},
    ]
    components["notifier"].send("Bot Alive", color=notifier_mod.COLOR_INFO, fields=fields)


def send_daily_summary(components: dict) -> None:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    rows = components["db"].uploads_since(since)
    # database.uploads_since() returns (video_id, upload_date, uploaded_video_id, title) -> title is index 3
    fields = [
        {"name": "New Shorts Found / Uploaded", "value": str(len(rows))},
        {"name": "Titles", "value": "\n".join(r[3] for r in rows) or "none"},
    ]
    components["notifier"].send("Daily Report", color=notifier_mod.COLOR_INFO, fields=fields)


def main() -> None:
    components: dict | None = None
    try:
        # Do not authenticate during construction: an expired token and an
        # offline router used to make the whole app exit before the scheduler
        # had a chance to wait for Wi-Fi.
        components = build_app(authenticate=False)
        state = components["state"]
        notifier = components["notifier"]

        stop_event = threading.Event()

        def handle_signal(signum, frame):
            stop_event.set()

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        if not state.clean_shutdown:
            notifier.send(
                "Application restarted after crash",
                f"Last task: {state.current_task}",
                color=notifier_mod.COLOR_WARNING,
            )
        state.clean_shutdown = False
        components["state_mgr"].save(state)

        notifier.send("Program started", color=notifier_mod.COLOR_SUCCESS)

        if not authenticate_when_online(components, stop_event):
            notifier.send("Application shutting down", "stop requested before authentication")
            notifier.shutdown()
            components["db"].close()
            return

        if not self_test(components):
            notifier.send("Application shutting down", "self-test failed", color=notifier_mod.COLOR_ERROR)
            notifier.shutdown()
            sys.exit(1)

        components["downloader"].cleanup(None)  # purge stale temp files from a previous run

        sched = scheduler_mod.Scheduler(
            lambda: run_cycle(components),
            components["config"]["check_interval_minutes"],
            notifier,
            stop_event,
            heartbeat_fn=lambda: send_heartbeat(components),
            summary_fn=lambda: send_daily_summary(components),
        )
        sched.run_forever()

        state.clean_shutdown = True
        state.current_task = "idle"
        components["state_mgr"].save(state)
        notifier.send("Application shutting down", color=notifier_mod.COLOR_WARNING)
        notifier.shutdown()
        components["db"].close()
    except Exception as exc:  # noqa: BLE001 - last-resort catch-all for the whole app
        log.critical("Fatal error in main: %s", exc, exc_info=True)
        if components is not None:
            try:
                components["notifier"].error(exc, "main", "startup")
            except Exception:
                pass
            try:
                components["notifier"].shutdown()
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
