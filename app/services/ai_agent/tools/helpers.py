"""
Shared helpers for AI agent tool functions.

Re-exports :mod:`app.services.ai_agent.deps` for backward-compatible imports.
"""
from __future__ import annotations

from app.services.ai_agent.deps import (  # noqa: F401
    AgentDeps,
    _user_schema,
    run_with_short_db_session,
)

__all__ = ["AgentDeps", "_user_schema", "run_with_short_db_session"]
