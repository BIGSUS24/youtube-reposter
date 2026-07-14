"""Shared types, exceptions, and helpers."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml


class AppError(Exception):
    """Base for all custom exceptions."""


class InsufficientDiskSpaceError(AppError):
    """Raised by check_disk_space when free space is below the threshold."""


class ConfigError(AppError):
    """Bad or missing config keys."""


@dataclass(frozen=True)
class VideoInfo:
    video_id: str
    title: str
    description: str
    duration_seconds: int
    published_at: str  # ISO UTC
    thumbnail_url: str
    source_channel_id: str = ""
    source_channel_name: str = ""


# Dotted paths of every required config key.
_REQUIRED_KEYS: tuple[str, ...] = (
    "destination_channel.oauth_client_json",
    "destination_channel.token_json",
    "download_folder",
    "database",
    "log_folder",
    "check_interval_minutes",
    "max_retry_attempts",
    "retry_delay_seconds",
    "delete_download_after_upload",
    "discord.enabled",
    "discord.webhook_url",
)


def _get_dotted(data: dict, dotted: str) -> object:
    node: object = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(dotted)
        node = node[part]
    return node


def load_config(path: Path) -> dict:
    """Load and validate config.yaml; raise ConfigError listing any missing keys."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Config root must be a mapping, got {type(raw).__name__}")

    missing = [key for key in _REQUIRED_KEYS if _is_missing(raw, key)]
    if missing:
        raise ConfigError("Missing config keys: " + ", ".join(missing))
    raw["source_channels"] = normalize_source_channels(raw)
    raw["max_shorts_per_channel_per_cycle"] = normalize_cycle_limit(raw)
    return raw


def _is_missing(data: dict, dotted: str) -> bool:
    try:
        _get_dotted(data, dotted)
        return False
    except KeyError:
        return True


def normalize_source_channels(config: dict) -> list[dict[str, str]]:
    """Return 1-5 source channels from either old or new config format."""
    raw_sources = config.get("source_channels")

    if raw_sources is None:
        legacy = config.get("source_channel")
        if not isinstance(legacy, dict) or not legacy.get("channel_id"):
            raise ConfigError(
                "Missing config keys: source_channels or source_channel.channel_id"
            )
        raw_sources = [legacy]

    if not isinstance(raw_sources, list):
        raise ConfigError("source_channels must be a list")
    if not raw_sources:
        raise ConfigError("source_channels must contain at least 1 channel")
    if len(raw_sources) > 5:
        raise ConfigError("source_channels supports at most 5 channels")

    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_sources, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"source_channels[{index}] must be a mapping")
        channel_id = str(item.get("channel_id", "")).strip()
        if not channel_id:
            raise ConfigError(f"source_channels[{index}].channel_id is required")
        if channel_id in seen:
            raise ConfigError(f"Duplicate source channel_id: {channel_id}")
        seen.add(channel_id)
        name = str(item.get("name", "")).strip() or f"Source {index}"
        normalized.append({"channel_id": channel_id, "name": name})

    return normalized


def normalize_cycle_limit(config: dict) -> int:
    raw_limit = config.get("max_shorts_per_channel_per_cycle", 1)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise ConfigError("max_shorts_per_channel_per_cycle must be an integer") from exc
    if not 1 <= limit <= 5:
        raise ConfigError("max_shorts_per_channel_per_cycle must be between 1 and 5")
    return limit


def atomic_write(path: Path, data: str) -> None:
    """Write durably: temp file in same dir, flush+fsync, then os.replace."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def check_disk_space(path: Path, min_free_mb: int = 500) -> None:
    """Raise InsufficientDiskSpaceError if free space at path is below min_free_mb."""
    free_mb = shutil.disk_usage(path).free // (1024 * 1024)
    if free_mb < min_free_mb:
        raise InsufficientDiskSpaceError(f"{free_mb}MB free, need {min_free_mb}MB")


def human_size(nbytes: int) -> str:
    """Format a byte count as e.g. '12.4 MB'."""
    size = float(nbytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024 or unit == "PB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"  # unreachable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
