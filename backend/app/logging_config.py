"""
Structured JSON logging configuration.

Produces one JSON object per log line — parseable by Datadog, ELK, CloudWatch, etc.
Set LOG_LEVEL env var to override (default: INFO).
Set LOG_FORMAT=text for human-readable output during local development.
"""

import logging
import logging.config
import os


class _JsonFormatter(logging.Formatter):
    """Minimal JSON formatter — no extra dependencies."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime, timezone

        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", "json").lower()

    handler: logging.Handler
    if log_format == "text":
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s | %(message)s")
        )
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "json" if log_format != "text" else "text",
            }
        },
        "formatters": {
            "json": {"()": _JsonFormatter},
            "text": {
                "format": "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
            },
        },
        "root": {
            "handlers": ["default"],
            "level": log_level,
        },
        "loggers": {
            # Silence noisy libraries
            "uvicorn.access": {"level": "WARNING", "propagate": True},
            "httpx": {"level": "WARNING", "propagate": True},
            "sqlalchemy.engine": {"level": "WARNING", "propagate": True},
            # Security events at INFO so they always appear
            "smartstudy.security": {"level": "INFO", "propagate": True},
        },
    })
