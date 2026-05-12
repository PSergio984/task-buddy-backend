import logging
from logging.config import dictConfig

from app.config import DevConfig, ProdConfig, config


def obfuscated(email: str, obfuscated_length: int = 2) -> str:
    if "@" not in email:
        return email  # Not a valid email, return as is

    local_part, domain = email.split("@", 1)
    if len(local_part) <= obfuscated_length:
        obfuscated_local = "*" * len(local_part)
    else:
        obfuscated_local = local_part[:obfuscated_length] + "*" * (
            len(local_part) - obfuscated_length
        )
    return f"{obfuscated_local}@{domain}"


class EmailObfuscationFilter(logging.Filter):
    def __init__(self, name: str = "", obfuscated_length: int = 2):
        super().__init__(name)
        self.obfuscated_length = obfuscated_length

    def filter(self, record: logging.LogRecord) -> bool:
        email = getattr(record, "email", None)
        if isinstance(email, str):
            record.email = obfuscated(email, self.obfuscated_length)
        return True


handlers = ["default", "rotating_file"]
if isinstance(config, DevConfig):
    handlers.append("sentryHandler")


def configure_logging():
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
                    "format": "(%(correlation_id)s)%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                },
                "file": {
                    "class": "pythonjsonlogger.jsonlogger.JsonFormatter",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                    "format": "%(asctime)s %(msecs)03d %(levelname)s %(name)s %(lineno)d %(correlation_id)s %(message)s",
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
                    "handlers": handlers,
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
