"""Logging configuration: obfuscation helpers, filters, and dictConfig setup.

Email values are redacted before they reach handlers; invalid values that
cannot be parsed as emails are fully masked rather than logged unchanged.
"""

import logging
from logging.config import dictConfig

from app.config import DevConfig, ProdConfig, config

REDACTED_MARKER = "***"


def obfuscated(email: str, obfuscated_length: int = 2) -> str:
    """Redact an email address, keeping the first ``obfuscated_length`` local chars.

    Values that are not valid single-``@`` emails (empty local or domain part,
    extra ``@`` characters, whitespace) are fully masked.
    """
    if email.count("@") != 1:
        return REDACTED_MARKER

    local_part, domain = email.split("@", 1)
    if not local_part or not domain or any(ch.isspace() for ch in email):
        return REDACTED_MARKER

    if len(local_part) <= obfuscated_length:
        obfuscated_local = "*" * len(local_part)
    else:
        obfuscated_local = local_part[:obfuscated_length] + "*" * (
            len(local_part) - obfuscated_length
        )
    return f"{obfuscated_local}@{domain}"


class EmailObfuscationFilter(logging.Filter):
    """Rewrite the ``email`` field of log records with a redacted value."""

    def __init__(self, name: str = "", obfuscated_length: int = 2) -> None:
        super().__init__(name)
        self.obfuscated_length = obfuscated_length

    def filter(self, record: logging.LogRecord) -> bool:
        email = getattr(record, "email", None)
        if isinstance(email, str):
            record.email = obfuscated(email, self.obfuscated_length)
        return True


def _handler_names() -> list:
    """Return the enabled handler names for the ``app`` logger."""
    names = ["default", "rotating_file"]
    if isinstance(config, DevConfig):
        names.append("sentryHandler")
    return names


def configure_logging() -> None:
    """Apply the application logging configuration via dictConfig."""
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "correlation_id": {
                    "()": "asgi_correlation_id.CorrelationIdFilter",
                    "uuid_length": 8 if isinstance(config, DevConfig) else 32,
                    "default_value": "-",
                },
                "email_obfuscation": {
                    "()": EmailObfuscationFilter,
                    "obfuscated_length": 2 if isinstance(config, DevConfig) else 0,
                },
            },
            "formatters": {
                "console": {
                    "class": "logging.Formatter",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                    "format": (
                        "(%(correlation_id)s)%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                    ),
                },
                "file": {
                    "class": "pythonjsonlogger.jsonlogger.JsonFormatter",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                    "format": (
                        "%(asctime)s %(msecs)03d %(levelname)s %(name)s "
                        "%(lineno)d %(correlation_id)s %(message)s"
                    ),
                },
            },
            "handlers": {
                "default": {
                    "class": "rich.logging.RichHandler",
                    "level": "DEBUG",
                    "formatter": "console",
                    "filters": ["correlation_id", "email_obfuscation"],
                },
                "rotating_file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "level": "DEBUG",
                    "formatter": "file",
                    "filename": "app.log",
                    "maxBytes": 1024 * 1024,  # 1 MB
                    "backupCount": 5,
                    "encoding": "utf-8",
                    "filters": ["correlation_id", "email_obfuscation"],
                },
                "sentryHandler": {
                    "class": "sentry_sdk.integrations.logging.EventHandler",
                    "level": "DEBUG",
                    "formatter": "console",
                    "filters": ["correlation_id", "email_obfuscation"],
                },
            },
            "loggers": {
                "uvicorn": {
                    "handlers": ["default", "rotating_file"],
                    "level": "INFO",
                    "propagate": False,
                },
                "app": {
                    "handlers": _handler_names(),
                    "level": "DEBUG" if not isinstance(config, ProdConfig) else "INFO",
                    "propagate": False,
                },
                "databases": {
                    "handlers": ["default"],
                    "level": "DEBUG" if isinstance(config, DevConfig) else "WARNING",
                    "propagate": False,
                },
                "aiosqlite": {
                    "handlers": ["default"],
                    "level": "DEBUG" if isinstance(config, DevConfig) else "WARNING",
                    "propagate": False,
                },
            },
        }
    )
