"""Who may see a listing owner's phone number."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.models.enums import UserRole
from app.schemas.property import Property as PropertySchema
from app.schemas.visit import Visit as VisitSchema


def _may_see(prop: PropertySchema, viewer: Any | None) -> bool:
    if viewer is None:
        return False
    return viewer.id == prop.owner_id or getattr(viewer, "role", None) == UserRole.admin.value


def hide_owner_contact(prop: PropertySchema, viewer: Any | None) -> PropertySchema:
    """Return the listing without owner_contact, unless the viewer is its owner or an admin.

    Public visitors reach the listing owner through the assigned agent (``agent``) or
    through POST /leads, not through the owner's own number.
    """
    if prop.owner_contact is None or _may_see(prop, viewer):
        return prop
    return prop.model_copy(update={"owner_contact": None})


def hide_owner_contacts(props: Iterable[PropertySchema], viewer: Any | None) -> list[PropertySchema]:
    return [hide_owner_contact(p, viewer) for p in props]


# Ways to reach a visit's counterparty. Only the property owner, an admin or the
# counterparty themselves see these; id, name and avatar stay visible to everyone.
_COUNTERPARTY_CONTACT_FIELDS = ("email", "phone", "current_latitude", "current_longitude")


def hide_visit_contacts(visit: VisitSchema, viewer: Any | None) -> VisitSchema:
    """Apply ``hide_owner_contact`` to the nested property and hide the counterparty's contact."""
    prop, other = visit.property, visit.counterparty_user
    update: dict[str, Any] = {}
    if prop is not None:
        update["property"] = hide_owner_contact(prop, viewer)
    if other is not None:
        may_see = viewer is not None and (
            viewer.id == other.id or (prop is not None and _may_see(prop, viewer))
        )
        if not may_see:
            update["counterparty_user"] = other.model_copy(
                update=dict.fromkeys(_COUNTERPARTY_CONTACT_FIELDS)
            )
    return visit.model_copy(update=update) if update else visit


def hide_visits_contacts(visits: Iterable[VisitSchema], viewer: Any | None) -> list[VisitSchema]:
    return [hide_visit_contacts(v, viewer) for v in visits]
