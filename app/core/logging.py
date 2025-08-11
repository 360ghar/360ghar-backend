import logging
from logging.config import dictConfig

from app.core.config import settings


def setup_logging() -> None:
    """Configure application-wide logging.

    - Structured, concise console logs
    - Log level based on environment and DEBUG flag
    - Quiet noisy third-party loggers
    """
    level = "DEBUG" if settings.DEBUG else ("INFO" if settings.ENVIRONMENT != "production" else "INFO")

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "level": level,
                }
            },
            "root": {"handlers": ["console"], "level": level},
            "loggers": {
                # Quiet noisy libraries
                "uvicorn": {"level": "WARNING"},
                "uvicorn.error": {"level": "WARNING"},
                "uvicorn.access": {"level": "WARNING"},
                "httpx": {"level": "WARNING"},
                "asyncio": {"level": "WARNING"},
                # SQLAlchemy engine debug can be very noisy; keep at INFO unless DEBUG
                "sqlalchemy.engine": {"level": "INFO" if not settings.DEBUG else "DEBUG"},
            },
        }
    )


def get_logger(name: str) -> logging.Logger:
    """Convenience accessor for module-level loggers."""
    return logging.getLogger(name)


