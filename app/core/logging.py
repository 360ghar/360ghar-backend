import logging
import sys
from logging.config import dictConfig
from typing import Any, Dict

from app.core.config import settings


class ColorFormatter(logging.Formatter):
    """Simple ANSI color formatter for terminal readability."""

    COLORS = {
        "RESET": "\033[0m",
        "DIM": "\033[2m",
        "BOLD": "\033[1m",
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[41m\033[97m",  # White on Red background
    }

    DEFAULT_ATTRS = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
    }

    def __init__(self, fmt: str, datefmt: str | None = None, use_colors: bool = True) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        # Build key=value suffix for custom extras
        extras: Dict[str, Any] = {
            k: v
            for k, v in record.__dict__.items()
            if k not in self.DEFAULT_ATTRS and not k.startswith("_")
        }
        suffix = ""
        if extras:
            # Render extras compactly: key=value key2=value2
            parts = []
            for k, v in extras.items():
                try:
                    parts.append(f"{k}={v}")
                except Exception:
                    parts.append(f"{k}=?")
            suffix = " " + " ".join(parts)

        base = super().format(record)
        if not self.use_colors:
            return base + suffix

        level = record.levelname
        color = self.COLORS.get(level, "")
        reset = self.COLORS["RESET"]
        bold = self.COLORS["BOLD"]

        # Colorize level and name, keep message readable
        return base.replace(
            record.levelname, f"{bold}{color}{record.levelname}{reset}"
        ) + suffix


def setup_logging() -> None:
    """Configure application-wide logging with colorized console for TTY.

    - Color output for local terminals; plain text elsewhere
    - Log level based on DEBUG flag
    - Quiet noisy third-party loggers
    """
    level = "DEBUG" if settings.DEBUG else "INFO"
    is_tty = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
    use_colors = is_tty and settings.ENVIRONMENT != "production"

    format_string = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    date_format = "%H:%M:%S" if use_colors else "%Y-%m-%dT%H:%M:%S%z"

    # Build handler config dynamically to select formatter
    handlers = {
        "console": {
            "class": "logging.StreamHandler",
            "level": level,
        }
    }

    formatters = {
        "standard": {
            "format": format_string,
            "datefmt": date_format,
        }
    }

    if use_colors:
        formatters["color"] = {
            "()": "app.core.logging.ColorFormatter",
            "fmt": format_string,
            "datefmt": date_format,
            "use_colors": True,
        }
        handlers["console"]["formatter"] = "color"
    else:
        handlers["console"]["formatter"] = "standard"

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": formatters,
            "handlers": handlers,
            "root": {"handlers": ["console"], "level": level},
            "loggers": {
                # Quiet noisy libraries
                "uvicorn": {"level": "WARNING"},
                "uvicorn.error": {"level": "WARNING"},
                "uvicorn.access": {"level": "WARNING"},
                "httpx": {"level": "WARNING"},
                "asyncio": {"level": "WARNING"},
                # SQLAlchemy engine logs are noisy; raise level to WARNING to suppress SQL statements
                "sqlalchemy.engine": {"level": "WARNING"},
                # Be explicit for the concrete Engine logger as well
                "sqlalchemy.engine.Engine": {"level": "WARNING"},
            },
        }
    )


def get_logger(name: str) -> logging.Logger:
    """Convenience accessor for module-level loggers."""
    return logging.getLogger(name)


