import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_LOGGERS = {}


def setup_logger(
    name: str = "mexc_scanner",
    log_dir: str = "logs",
    log_file: str = "scanner.log",
    level: str = "INFO",
) -> logging.Logger:
    """Configure and return a structured logger with both console and rotating file output."""
    if name in _LOGGERS:
        return _LOGGERS[name]

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(log_dir) / log_file

    logger = logging.getLogger(name)
    num_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(num_level)
    logger.propagate = False

    # Avoid duplicate handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    # Formatter
    file_format = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s:%(funcName)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        import colorlog

        console_format = colorlog.ColoredFormatter(
            "%(log_color)s[%(asctime)s] [%(levelname)-8s]%(reset)s %(blue)s[%(name)s]%(reset)s %(message)s",
            datefmt="%H:%M:%S",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        )
    except ImportError:
        console_format = file_format

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_format)
    console_handler.setLevel(num_level)
    logger.addHandler(console_handler)

    # Rotating File Handler (10MB per file, 5 backups)
    file_handler = RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(file_format)
    file_handler.setLevel(num_level)
    logger.addHandler(file_handler)

    _LOGGERS[name] = logger
    return logger


def get_logger(name: str = "mexc_scanner") -> logging.Logger:
    """Retrieve an existing logger or create a default one."""
    if name in _LOGGERS:
        return _LOGGERS[name]
    return setup_logger(name)
