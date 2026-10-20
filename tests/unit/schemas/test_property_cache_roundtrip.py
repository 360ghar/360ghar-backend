from datetime import datetime, timezone

from app.schemas.property import Property, PropertyAgent, PropertyDetail

BASE = {
    "id": 1,
    "owner_id": 2,
    "title": "3 BHK",
    "property_type": "apartment",
    "purpose": "buy",
    "base_price": 1000000,
    "status": "available",
    "is_available": True,
    "view_count": 0,
    "like_count": 0,
    "interest_count": 0,
    "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
}


def test_cached_detail_keeps_amenities_and_agent():
    """get_property caches model_dump() and reads it back with model_validate()."""
    prop = PropertyDetail.model_validate(
        {
            **BASE,
            "property_amenities": [{"id": 5, "title": "Gym", "icon": "dumbbell", "category": "recreation"}],
            "agent": {"id": 9, "name": "Asha", "contact_number": "9876543210"},
        }
    )
    assert [a.title for a in prop.amenities] == ["Gym"]

    again = Property.model_validate(prop.model_dump(mode="json"))
    assert [a.title for a in again.amenities] == ["Gym"]
    assert again.agent == PropertyAgent(id=9, name="Asha", contact_number="9876543210", avatar_url=None)
