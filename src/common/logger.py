"""Logging configuration and shared logger setup."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from config.settings import get_settings


def setup_logger(name: str = "lesson_with_ai") -> logging.Logger:
    """Configure and return a standardized logger instance.

    Writes INFO/DEBUG logs to a rotating file in logs/ and outputs formatted
    logs to the console stream.
    """
    settings = get_settings()
    log_dir = settings.paths.logs_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    logger = logging.getLogger(name)

    # Avoid duplicate handlers if setup_logger is called repeatedly
    if logger.hasHandlers():
        return logger

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger.setLevel(log_level)

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s:%(funcName)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Rotating File Handler (5 MB per file, max 5 backups)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
