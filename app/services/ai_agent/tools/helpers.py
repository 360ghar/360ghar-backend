"""
Shared helpers for AI agent tool functions.

Contains the dependency container (``AgentDeps``) and common
serialization/auth utilities used across all tool modules.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.models.users import User

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Dependency container passed through RunContext
# ---------------------------------------------------------------------------

@dataclass
class AgentDeps:
    """Injected into every tool call via ``RunContext``."""

    user: User  # SQLAlchemy User model instance
    db: AsyncSession
    user_role: str  # "user", "agent", "admin"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _user_schema(user: User):
    """Convert a SQLAlchemy User to the Pydantic UserSchema expected by services."""
    from app.schemas.user import User as UserSchema
    return UserSchema.model_validate(user)
