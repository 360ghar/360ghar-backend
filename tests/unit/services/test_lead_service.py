from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import PropertyNotFoundException
from app.schemas.lead import LeadCreate
from app.services.lead import create_lead


def _db(prop=object()):
    db = MagicMock()
    db.get = AsyncMock(return_value=prop)
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_honeypot_stores_nothing():
    db = _db()
    await create_lead(db, LeadCreate(phone="9876543210", website="bot"), None)
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_lead_is_stored_with_the_user():
    db = _db()
    await create_lead(db, LeadCreate(phone="9876543210", property_id=7, note="Evening"), 42)
    lead = db.add.call_args.args[0]
    assert (lead.property_id, lead.user_id, lead.phone, lead.note) == (7, 42, "9876543210", "Evening")
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_property_is_rejected():
    db = _db(prop=None)
    with pytest.raises(PropertyNotFoundException):
        await create_lead(db, LeadCreate(phone="9876543210", property_id=999), None)
    db.add.assert_not_called()
