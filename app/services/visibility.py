"""Who sees which user and contact data.

- Owner contact goes to the listing owner and admins. Other viewers see the
  assigned agent's number, or the company number when no agent is assigned.
- A visit counterparty's contact details (email, phone, location) go to the
  counterparty, the listing owner and admins. Everyone else sees name and avatar.
- A user embedded in another record (the tenant or owner of a lease, an applicant) is a
  PublicUserRef. phone and email go to the record's owner, admins and the user themself.
- A listing's moderation fields (moderated_by, moderation_reason, ai_prescreen_*,
  auto_paused_*, ...) go to admins only. Everyone else gets the allowlist
  PUBLIC_LISTING_PREFERENCE_KEYS.

Masking functions accept ORM objects, Pydantic models and dicts, and never change
the input.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from app.config import settings
from app.models.enums import UserRole
from app.schemas.base import PublicUserRef

T = TypeVar("T")

_COUNTERPARTY_CONTACT_FIELDS = ("email", "phone", "current_latitude", "current_longitude")

# Keys of properties.listing_preferences that non-admin viewers may see. Any other key,
# including every moderator key, is removed for them.
PUBLIC_LISTING_PREFERENCE_KEYS = frozenset(
    {
        "gender_preference",
        "sharing_type",
        "moderation_status",
        "video_tour_url",
        "expires_at",
        "food_habits",
        "smoking_drinking",
        "guests_policy",
        "cleanliness",
        "pets",
        "parties_at_home",
        "society_type",
        "society_amenities",
        "society_vibe_tags",
        # Room-level furnishing. furnishing_level is derived from it (property/helpers.py).
        "rooms",
    }
)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def name_in(obj: Any, name: str) -> bool:
    """True when ``obj`` has ``name`` as a key (dict) or attribute (object)."""
    if isinstance(obj, Mapping):
        return name in obj
    return hasattr(obj, name)


def _role_value(user: Any) -> Any:
    role = _get(user, "role")
    return getattr(role, "value", role)


@dataclass(frozen=True)
class Viewer:
    """The caller of a request. ``user`` is None for anonymous callers."""

    user: Any | None = None
    is_admin: bool = False
    is_agent: bool = False

    @classmethod
    def from_user(cls, user: Any | None) -> Viewer:
        if user is None:
            return cls()
        role = _role_value(user)
        return cls(
            user=user, is_admin=role == UserRole.admin.value, is_agent=role == UserRole.agent.value
        )

    @property
    def id(self) -> int | None:
        return None if self.user is None else _get(self.user, "id")


def as_viewer(viewer: Viewer | Any | None) -> Viewer:
    """Accept a Viewer or a raw user (ORM, Pydantic or None)."""
    return viewer if isinstance(viewer, Viewer) else Viewer.from_user(viewer)


def is_owner(viewer: Viewer | Any | None, obj: Any) -> bool:
    uid = as_viewer(viewer).id
    return uid is not None and uid == _get(obj, "owner_id")


def is_counterparty(viewer: Viewer | Any | None, obj: Any) -> bool:
    uid = as_viewer(viewer).id
    other = _get(obj, "counterparty_user_id")
    if other is None:
        other = _get(_get(obj, "counterparty_user"), "id")
    return uid is not None and uid == other


def is_matched(viewer: Viewer | Any | None, matched: bool | Callable[[], bool]) -> bool:
    """True when the viewer is signed in and the match check passes (a flag or a callable)."""
    if as_viewer(viewer).user is None:
        return False
    return matched if isinstance(matched, bool) else bool(matched())


def _replace(obj: T, updates: dict[str, Any]) -> T:
    if isinstance(obj, BaseModel):
        return obj.model_copy(update=updates)
    if isinstance(obj, Mapping):
        return {**obj, **updates}  # type: ignore[return-value]
    return _Overlay(obj, updates)  # type: ignore[return-value]


class _Overlay:
    """Read-only view of an ORM object with some attributes replaced."""

    def __init__(self, obj: Any, updates: dict[str, Any]) -> None:
        self._obj = obj
        self._updates = updates

    def __getattr__(self, name: str) -> Any:
        if name in self._updates:
            return self._updates[name]
        return getattr(self._obj, name)


def _agent_contact(prop: Any) -> str | None:
    agent = _get(prop, "agent")
    return _get(agent, "contact_number") if agent is not None else None


def public_listing_preferences(prefs: Any) -> dict[str, Any]:
    """The allowlisted keys of a listing_preferences value (model, dict or None)."""
    if prefs is None:
        return {}
    raw = prefs.model_dump(exclude_none=True) if isinstance(prefs, BaseModel) else dict(prefs)
    return {k: v for k, v in raw.items() if k in PUBLIC_LISTING_PREFERENCE_KEYS}


def mask_listing_preferences(prop: T, viewer: Viewer | Any | None) -> T:
    """Remove moderator keys from listing_preferences unless the viewer is an admin.

    Use this for every listing read, including peer payloads of other users.
    """
    v = as_viewer(viewer)
    if v.is_admin or not name_in(prop, "listing_preferences"):
        return prop
    prefs = _get(prop, "listing_preferences")
    if prefs is None:
        return prop
    filtered = public_listing_preferences(prefs)
    # Keep the model type for pydantic objects, so the response shape does not change.
    value: Any = type(prefs).model_validate(filtered) if isinstance(prefs, BaseModel) else filtered
    return _replace(prop, {"listing_preferences": value})


def mask_owner_contact(prop: T, viewer: Viewer | Any | None) -> T:
    """Show the owner's contact only to the owner and admins. Others get the agent's or company number.

    Also applies ``mask_listing_preferences``, so one call masks a listing for a viewer.
    """
    v = as_viewer(viewer)
    updates: dict[str, Any] = {}
    if name_in(prop, "owner_contact") and not (is_owner(v, prop) or v.is_admin):
        replacement = _agent_contact(prop) or settings.COMPANY_CONTACT_NUMBER
        if replacement != _get(prop, "owner_contact"):
            updates["owner_contact"] = replacement
    masked = mask_listing_preferences(prop, v)
    if masked is not prop:
        updates["listing_preferences"] = _get(masked, "listing_preferences")
    return _replace(prop, updates) if updates else prop


def mask_owner_contacts(props: Iterable[T], viewer: Viewer | Any | None) -> list[T]:
    return [mask_owner_contact(p, viewer) for p in props]


def mask_visit_contacts(visit: T, viewer: Viewer | Any | None) -> T:
    """Apply ``mask_owner_contact`` to the nested property and hide the counterparty's contact."""
    return cast(T, _mask_visit(cast(Any, visit), viewer))


def _mask_visit(visit: Any, viewer: Viewer | Any | None) -> Any:
    v = as_viewer(viewer)
    prop, other = _get(visit, "property"), _get(visit, "counterparty_user")
    update: dict[str, Any] = {}
    if prop is not None:
        update["property"] = mask_owner_contact(prop, v)
    if other is not None:
        may_see = v.user is not None and (
            v.id == _get(other, "id") or (prop is not None and (v.is_admin or is_owner(v, prop)))
        )
        if not may_see:
            update["counterparty_user"] = _replace(
                other, dict.fromkeys(_COUNTERPARTY_CONTACT_FIELDS)
            )
    return _replace(visit, update) if update else visit


def mask_visits_contacts(visits: Iterable[T], viewer: Viewer | Any | None) -> list[T]:
    return [mask_visit_contacts(v, viewer) for v in visits]


def mask_user_ref(
    user: Any, viewer: Viewer | Any | None, *, owner_id: int | None
) -> dict[str, Any] | None:
    """A user embedded in another record, as a dict (None when there is no user).

    Every viewer gets the PublicUserRef fields: id, display_name, avatar_url. ``phone`` and
    ``email`` are added only for the owner of the record (``owner_id``), for admins and for
    the user themself. An assigned agent who is not the owner gets no contact data.
    """
    if user is None:
        return None
    v = as_viewer(viewer)
    ref = PublicUserRef.model_validate(
        {
            "id": _get(user, "id"),
            "full_name": _get(user, "full_name"),
            "profile_image_url": _get(user, "profile_image_url"),
        }
    ).model_dump()
    uid = v.id
    if v.is_admin or (uid is not None and uid in (owner_id, _get(user, "id"))):
        ref["phone"] = _get(user, "phone")
        ref["email"] = _get(user, "email")
    return ref
