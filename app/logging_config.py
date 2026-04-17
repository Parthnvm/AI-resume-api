"""
app/logging_config.py — Structured logging configuration.

- Production: JSON-formatted lines (parseable by Render, Datadog, CloudWatch, etc.)
- Development: Human-readable with colour-friendly format
- Log level is controlled by LOG_LEVEL env var (default: INFO)
"""

import logging
import sys
import json
import os
from datetime import datetime, timezone


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts":      datetime.now(tz=timezone.utc).isoformat(),
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _DevFormatter(logging.Formatter):
    """Readable log format for local development."""
    FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    DATEFMT = "%H:%M:%S"

    def __init__(self):
        super().__init__(fmt=self.FMT, datefmt=self.DATEFMT)


def configure_logging(debug: bool = False) -> None:
    """
    Configure root logger and Flask/Werkzeug loggers.

    Call this once from create_app() before registering routes.
    """
    level_name = os.environ.get("LOG_LEVEL", "DEBUG" if debug else "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_DevFormatter() if debug else _JsonFormatter())

    root = logging.getLogger()
    # Avoid duplicate handlers when app factory is called multiple times in tests
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quieten noisy third-party loggers in production
    if not debug:
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
