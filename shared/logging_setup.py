"""Structured logging with rotating file audit logs and optional UI listener."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable


class CallbackLogHandler(logging.Handler):
    """Forwards formatted log records to a UI callback."""

    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._callback(self.format(record))
        except Exception:
            pass


def setup_logging(
    log_dir: Path,
    app_name: str,
    ui_callback: Callable[[str], None] | None = None,
) -> logging.Logger:
    """Configure rotating file + stderr + optional UI logging."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("classroom_manager")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_dir / f"{app_name}.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    if ui_callback is not None:
        cb_handler = CallbackLogHandler(ui_callback)
        cb_handler.setFormatter(fmt)
        logger.addHandler(cb_handler)

    return logger
