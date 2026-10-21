from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PropertyNotFoundException
from app.core.logging import get_logger
from app.models.leads import Lead
from app.models.properties import Property
from app.schemas.lead import LeadCreate
from app.schemas.pagination import keyset_filter, trim_keyset_lookahead, validate_keyset_payload

logger = get_logger(__name__)


async def list_leads(
    db: AsyncSession, cursor_payload: dict[str, Any], limit: int, *, with_total: bool = False
) -> tuple[list[Lead], dict[str, Any] | None, int | None]:
    """Stored callback requests, newest first. Admin use only. No filters yet."""
    total: int | None = None
    if with_total:
        total = (await db.execute(select(func.count(Lead.id)))).scalar_one()
    # leads.id is int4 (SERIAL), so a cursor id outside that range gives 400, not a 500.
    validate_keyset_payload(cursor_payload, "datetime", id_kind="int4")
    predicate = keyset_filter(Lead.created_at, Lead.id, cursor_payload, descending=True)
    stmt = select(Lead).order_by(Lead.created_at.desc(), Lead.id.desc()).limit(limit + 1)
    if predicate is not None:
        stmt = stmt.where(predicate)
    rows = list((await db.execute(stmt)).scalars().all())
    page, next_payload = trim_keyset_lookahead(
        rows,
        limit=limit,
        sort_value=lambda lead: lead.created_at,
        item_id=lambda lead: lead.id,
    )
    return page, next_payload, total


async def create_lead(db: AsyncSession, data: LeadCreate, user_id: int | None) -> int | None:
    """Store a callback request and return its id. A filled honeypot stores nothing and returns None."""
    if data.website:
        logger.info("Lead dropped: honeypot filled")
        return None
    # An id outside BIGINT cannot be bound to the primary key, so it is simply not found.
    if data.property_id is not None and (
        not 0 < data.property_id < 2**63 or await db.get(Property, data.property_id) is None
    ):
        raise PropertyNotFoundException(property_id=data.property_id)
    lead = Lead(
        property_id=data.property_id,
        user_id=user_id,
        name=data.name,
        phone=data.phone,
        note=data.note,
    )
    db.add(lead)
    # Flush first: reading lead.id after commit would lazy-load on an async session.
    await db.flush()
    lead_id = lead.id
    await db.commit()
    logger.info(
        "Lead stored", extra={"property_id": data.property_id, "signed_in": user_id is not None}
    )
    return lead_id
