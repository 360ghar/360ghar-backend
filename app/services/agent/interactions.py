from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utc_now
from app.models.agents import AgentInteraction


async def get_daily_interactions(db: AsyncSession, agent_id: int) -> int:
    """Get the count of interactions for an agent today."""
    today_start = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(func.count(AgentInteraction.id))
        .where(AgentInteraction.agent_id == agent_id)
        .where(AgentInteraction.created_at >= today_start)
    )
    result = await db.execute(stmt)
    return result.scalar() or 0


async def get_weekly_interactions(db: AsyncSession, agent_id: int) -> int:
    """Get the count of interactions for an agent in the last 7 days."""
    week_start = utc_now() - timedelta(days=7)
    stmt = (
        select(func.count(AgentInteraction.id))
        .where(AgentInteraction.agent_id == agent_id)
        .where(AgentInteraction.created_at >= week_start)
    )
    result = await db.execute(stmt)
    return result.scalar() or 0
