"""Logging filters to suppress expected control-flow exceptions from FastMCP."""
from __future__ import annotations

import logging


class AuthRequiredExcFilter(logging.Filter):
    """Drop ERROR logs emitted by FastMCP internals when a tool raises
    AuthRequiredError (a ToolError subclass handled by
    AppsSDKFastMCP._call_tool_mcp). These are expected control flow,
    not real errors, and produce noisy tracebacks in production.

    FastMCP may log from ``fastmcp.tools.tool``, ``fastmcp.tools.base``,
    or ``fastmcp.server.server``; attach this filter to all of them.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if exc is not None and exc.__class__.__name__ == "AuthRequiredError":
            return False
        # Rich-formatted FastMCP logs sometimes put the exception class in
        # the message without exc_info attached to this record.
        msg = record.getMessage() if hasattr(record, "getMessage") else str(record.msg)
        if "AuthRequiredError" in msg:
            return False
        return True
