from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from logging.config import dictConfig
from typing import Any

from app.config import settings

_current_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)


def set_request_id(request_id: str) -> contextvars.Token[str]:
    """Store the active request id for the current async context."""
    return _current_request_id.set(request_id)


def reset_request_id(token: contextvars.Token[str]) -> None:
    """Restore the previous request id context."""
    _current_request_id.reset(token)


def get_request_id() -> str:
    """Return the active request id, or an empty string outside a request."""
    return _current_request_id.get("")


class RequestIDFilter(logging.Filter):
    """Inject the current request id into log records.

    Defined here (in the logging module) rather than infrastructure to break
    the circular dependency: core/logging no longer needs to import from
    infrastructure at setup time.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = get_request_id()
        if request_id:
            record.request_id = request_id
        return True


class ColorFormatter(logging.Formatter):
    """Simple ANSI color formatter for terminal readability."""

    # Map internal logger names to cleaner display names
    NAME_MAP = {
        "uvicorn.error": "uvicorn",
        "uvicorn.access": "uvicorn",
    }

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
        "taskName",
        "processName",
        "process",
        "message",
        "asctime",
    }

    def __init__(self, fmt: str, datefmt: str | None = None, use_colors: bool = True) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        # Map logger name to cleaner display name
        display_name = self.NAME_MAP.get(record.name, record.name)
        original_name = record.name
        record.name = display_name

        # Build key=value suffix for custom extras
        extras: dict[str, Any] = {
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

        # Restore original name for other handlers
        record.name = original_name

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


class StructuredFormatter(logging.Formatter):
    """JSON formatter for production log aggregation."""

    # Reuse the same DEFAULT_ATTRS set so extra-field detection stays consistent
    DEFAULT_ATTRS = ColorFormatter.DEFAULT_ATTRS

    # Keys that should never be logged in plain text
    SENSITIVE_PATTERNS = {"password", "secret", "token", "api_key", "authorization", "cookie"}

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info),
            }

        # Add extra fields (anything not in DEFAULT_ATTRS)
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in self.DEFAULT_ATTRS and not k.startswith("_")
        }
        if extras:
            sanitized: dict[str, Any] = {}
            for k, v in extras.items():
                if any(s in k.lower() for s in self.SENSITIVE_PATTERNS):
                    sanitized[k] = "[REDACTED]"
                else:
                    try:
                        json.dumps(v)  # Test serializability
                        sanitized[k] = v
                    except (TypeError, ValueError):
                        sanitized[k] = str(v)
            log_entry["context"] = sanitized

        # Add request_id / correlation_id if available
        if hasattr(record, "request_id") and record.request_id:
            log_entry["correlation_id"] = record.request_id

        return json.dumps(log_entry, default=str)


def setup_logging() -> None:
    """Configure application-wide logging.

    - Production: structured JSON for machine parsing and log aggregation
    - Development + TTY: colorized human-readable output
    - Development + non-TTY (e.g. Docker): plain text
    - Log level based on DEBUG flag
    - Quiet noisy third-party loggers
    - RequestIDFilter attached to root handler for correlation-id propagation
    """
    level = "DEBUG" if settings.DEBUG else "INFO"
    is_production = settings.ENVIRONMENT == "production"
    is_tty = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
    use_colors = is_tty and not is_production

    format_string = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    date_format = "%H:%M:%S" if use_colors else "%Y-%m-%dT%H:%M:%S%z"

    # Build handler config dynamically to select formatter
    handlers = {
        "console": {
            "class": "logging.StreamHandler",
            "level": level,
            "stream": "ext://sys.stdout",
        }
    }

    formatters: dict[str, Any] = {
        "standard": {
            "format": format_string,
            "datefmt": date_format,
        }
    }

    if is_production:
        # Structured JSON logging for production
        formatters["structured"] = {
            "()": "app.core.logging.StructuredFormatter",
        }
        handlers["console"]["formatter"] = "structured"
    elif use_colors:
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
                "uvicorn": {"level": "INFO"},
                "uvicorn.error": {"level": "INFO"},
                "uvicorn.access": {"level": "INFO"},
                "httpx": {"level": "WARNING"},
                "asyncio": {"level": "WARNING"},
                # SQLAlchemy engine logs are noisy; raise level to WARNING to suppress SQL statements
                "sqlalchemy.engine": {"level": "WARNING"},
                # Be explicit for the concrete Engine logger as well
                "sqlalchemy.engine.Engine": {"level": "WARNING"},
                # User auth lookups fire on every request — suppress in production
                "app.services.user": {"level": "WARNING" if is_production else "DEBUG"},
            },
        }
    )

    # Attach RequestIDFilter to root handler so all log records carry correlation_id
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.addFilter(RequestIDFilter())


def get_logger(name: str) -> logging.Logger:
    """Convenience accessor for module-level loggers."""
    return logging.getLogger(name)
