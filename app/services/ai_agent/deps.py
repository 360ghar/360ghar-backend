"""AI agent dependency container and short-lived DB session helpers.

Kept outside ``tools/`` so unit tests can import without loading MCP/FastMCP.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.models.users import User

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass
class AgentDeps:
    """Injected into every tool call via ``RunContext``.

    Prefer ``session_factory`` so each tool opens a short-lived session and
    does not pin a Supavisor backend across multi-minute LLM waits. ``db`` is
    set for the duration of a single tool call (or injected in unit tests).
    """

    user: Any  # SQLAlchemy User model instance (or None for guests)
    user_role: str  # "user", "agent", "admin", "guest"
    db: AsyncSession | None = None
    session_factory: Callable[[], Any] | None = None

    @asynccontextmanager
    async def short_session(self) -> AsyncIterator[AsyncSession]:
        """Yield a DB session that lives only for one tool unit of work."""
        if self.session_factory is not None:
            async with self.session_factory() as session:
                try:
                    yield session
                    if session.new or session.dirty or session.deleted:
                        await session.commit()
                except Exception:
                    await session.rollback()
                    raise
            return
        if self.db is not None:
            yield self.db
            return
        raise RuntimeError("AgentDeps has neither session_factory nor db")


async def run_with_short_db_session(
    deps: AgentDeps,
    operation: Callable[[], Awaitable[T]],
) -> T:
    """Run ``operation`` with ``deps.db`` bound to a short-lived session.

    When ``session_factory`` is set, opens/closes a session for this call only.
    Otherwise uses the injected ``deps.db`` (tests / legacy callers).
    """
    if deps.session_factory is None:
        return await operation()

    async with deps.short_session() as session:
        previous = deps.db
        deps.db = session
        try:
            return await operation()
        finally:
            deps.db = previous


def _user_schema(user: User):
    """Convert a SQLAlchemy User to the Pydantic UserSchema expected by services."""
    from app.schemas.user import User as UserSchema

    return UserSchema.model_validate(user)
