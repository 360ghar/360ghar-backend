"""Logging filters to suppress expected control-flow exceptions from FastMCP."""
from __future__ import annotations

import logging


class AuthRequiredExcFilter(logging.Filter):
    """Drop ERROR logs emitted by FastMCP internals when a tool raises
    AuthRequiredError (a ToolError subclass handled by
    AppsSDKFastMCP._call_tool_mcp). These are expected control flow,
    not real errors, and produce noisy tracebacks in production."""

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if exc is not None and exc.__class__.__name__ == "AuthRequiredError":
            return False
        return True
