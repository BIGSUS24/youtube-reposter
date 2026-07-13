"""Logging setup: UTC-timestamped rotating file handlers + stdout."""

from __future__ import annotations

import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUPS = 3


def setup_logging(log_folder: Path, level: int = logging.INFO) -> None:
    log_folder.mkdir(parents=True, exist_ok=True)

    logging.Formatter.converter = time.gmtime  # asctime in UTC
    formatter = logging.Formatter(_FORMAT)

    def _rotating(name: str, handler_level: int) -> RotatingFileHandler:
        handler = RotatingFileHandler(
            log_folder / name, maxBytes=_MAX_BYTES, backupCount=_BACKUPS,
            encoding="utf-8",
        )
        handler.setLevel(handler_level)
        handler.setFormatter(formatter)
        return handler

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    root.addHandler(_rotating("app.log", logging.INFO))
    root.addHandler(_rotating("error.log", logging.ERROR))

    stream = logging.StreamHandler(sys.stdout)
    stream.setLevel(logging.INFO)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    upload = logging.getLogger("upload")
    upload.propagate = True
    upload.handlers.clear()
    upload.addHandler(_rotating("upload.log", logging.INFO))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
