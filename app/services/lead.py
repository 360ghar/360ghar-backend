from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PropertyNotFoundException
from app.core.logging import get_logger
from app.models.leads import Lead
from app.models.properties import Property
from app.schemas.lead import LeadCreate

logger = get_logger(__name__)


async def create_lead(db: AsyncSession, data: LeadCreate, user_id: int | None) -> None:
    """Store a callback request. A filled honeypot stores nothing."""
    if data.website:
        logger.info("Lead dropped: honeypot filled")
        return
    if data.property_id is not None and await db.get(Property, data.property_id) is None:
        raise PropertyNotFoundException(property_id=data.property_id)
    db.add(
        Lead(
            property_id=data.property_id,
            user_id=user_id,
            name=data.name,
            phone=data.phone,
            note=data.note,
        )
    )
    await db.commit()
    logger.info("Lead stored", extra={"property_id": data.property_id, "signed_in": user_id is not None})
