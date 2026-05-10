"""Backward-compatible request context imports.

The canonical implementation lives in app.core.logging so logging setup does
not depend on infrastructure modules.
"""

from app.core.logging import (
    RequestIDFilter,
    get_request_id,
    reset_request_id,
    set_request_id,
)

__all__ = ["RequestIDFilter", "get_request_id", "reset_request_id", "set_request_id"]
