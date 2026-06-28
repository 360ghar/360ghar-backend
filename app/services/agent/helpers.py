from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agents import Agent
from app.schemas.agent import Agent as AgentSchema


async def _paginate_agents(
    db: AsyncSession,
    base_stmt: Any,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    offset = (page - 1) * limit
    # Page rows
    page_stmt = base_stmt.offset(offset).limit(limit)
    result = await db.execute(page_stmt)
    rows = result.scalars().all()
    items = [AgentSchema.model_validate(r) for r in rows]

    # Total count
    count_stmt = base_stmt.with_only_columns(func.count(Agent.id)).order_by(None)
    count_result = await db.execute(count_stmt)
    total = int(count_result.scalar() or 0)

    total_pages = (total + limit - 1) // limit if limit else 1
    has_next = page < total_pages
    has_prev = page > 1 and total > 0

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": has_next,
        "has_prev": has_prev,
    }
