"""
Shared utilities for MCP servers.

Provides common helper functions for database access, user resolution,
and role-based authorization used across both User and Admin MCP servers.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from mcp.server.auth.middleware.auth_context import get_access_token as get_auth_access_token
from pydantic import TypeAdapter
from sqlalchemy import inspect
from sqlalchemy.exc import NoInspectionAvailable

from app.core.database import AsyncSessionLocalBG
from app.core.logging import get_logger
from app.models.enums import UserRole
from app.schemas.base import UtcDateTime
from app.services.user import get_user_by_id
from app.services.visibility import mask_owner_contact, mask_user_ref

if TYPE_CHECKING:
    from app.models.bookings import Booking
    from app.models.pm_finance import RentPayment
    from app.models.pm_leases import Lease
    from app.models.pm_maintenance import MaintenanceRequest
    from app.models.properties import Property
    from app.models.users import User
    from app.schemas.property import Property as PropertySchema

logger = get_logger(__name__)


async def get_db():
    """Async generator for database sessions using the background pool.

    MCP tool calls are typically long-lived and read-heavy. Using the
    background pool avoids competing with HTTP API requests for the
    limited main pool connections.
    """
    import sentry_sdk

    async with AsyncSessionLocalBG() as db:
        try:
            yield db
        except Exception as e:
            logger.error("MCP database session error: %s", e)
            sentry_sdk.set_context(
                "database",
                {
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            await db.rollback()
            raise
        else:
            await db.commit()


def get_user_role(user: User) -> UserRole:
    """Get the UserRole enum from a user object.

    The model column now stores a UserRole enum directly.
    Falls back to UserRole.user for objects that may still
    expose role as a plain string.
    """
    role = user.role
    if isinstance(role, UserRole):
        return role
    try:
        return UserRole(role)
    except ValueError:
        return UserRole.user


def is_admin(user: User) -> bool:
    """Check if user has admin role."""
    return get_user_role(user) == UserRole.admin


def is_agent(user: User) -> bool:
    """Check if user has agent role."""
    return get_user_role(user) == UserRole.agent


def is_owner_or_above(user: User) -> bool:
    """Check if user is at least a regular user (can own properties)."""
    role = get_user_role(user)
    return role in (UserRole.user, UserRole.agent, UserRole.admin)


def can_manage_property(user: User, property_owner_id: int) -> bool:
    """
    Check if user can manage a property (basic check without DB).

    For full authorization with agent scope, use pm_authz.assert_can_access_property.
    """
    role = get_user_role(user)
    if role == UserRole.admin:
        return True
    if property_owner_id == user.id:
        return True
    return False


async def get_user_from_mcp_context(db) -> User | None:
    """
    Resolve the current authenticated user for MCP tools.

    Uses OAuth access token from the MCP auth context.
    Supabase JWT authentication is no longer supported in MCP endpoints.

    Args:
        db: AsyncSession database connection

    Returns:
        User object or None if not authenticated
    """
    logger.debug("Resolving user from MCP auth context")
    access_token = get_auth_access_token()
    if access_token is None:
        logger.debug("No access token in MCP auth context")
        return None

    claims = getattr(access_token, "claims", {}) or {}
    auth_method = claims.get("auth_method")

    if auth_method != "oauth":
        logger.warning("Unsupported auth method in MCP context", extra={"auth_method": auth_method})
        return None

    user_id_raw = claims.get("sub") or claims.get("user_id")
    if not user_id_raw:
        logger.warning("OAuth access token missing user id claim")
        return None

    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        logger.warning("OAuth access token has invalid user id", extra={"user_id_raw": user_id_raw})
        return None

    user = await get_user_by_id(db, user_id)
    if user:
        logger.info("User resolved from MCP context", extra={"user_id": user.id, "role": user.role})
    else:
        logger.warning("OAuth access token refers to unknown user id", extra={"user_id": user_id})
    return user


def _money(value: Any) -> float | None:
    """Money as a JSON number (2 places). Decimal serializes as a string otherwise."""
    if value is None:
        return None
    return round(float(value), 2)


_UTC_DATETIME = TypeAdapter(UtcDateTime)


def utc_iso(value: datetime | date | None) -> str | None:
    """A datetime as UTC ISO 8601 with a Z suffix, the encoding REST responses use.

    A date-only value keeps its date form.
    """
    if value is None:
        return None
    if not isinstance(value, datetime):
        return value.isoformat()
    return str(_UTC_DATETIME.dump_python(value, mode="json"))


def serialize_property_basic(prop: Property | PropertySchema) -> dict:
    """Serialize a property object to basic dict for MCP responses."""
    property_type = getattr(prop, "property_type", None)
    purpose = getattr(prop, "purpose", None)
    status = getattr(prop, "status", None)
    management_status = getattr(prop, "management_status", None)
    created_at = getattr(prop, "created_at", None)

    return {
        "id": prop.id,
        "title": prop.title,
        "property_type": property_type.value if property_type else None,
        "purpose": purpose.value if purpose else None,
        "status": status.value if status else None,
        "city": prop.city,
        "locality": prop.locality,
        "full_address": getattr(prop, "full_address", None),
        "base_price": _money(prop.base_price),
        "price": _money(prop.base_price),
        "monthly_rent": _money(getattr(prop, "monthly_rent", None)),
        "daily_rate": _money(getattr(prop, "daily_rate", None)),
        "bedrooms": getattr(prop, "bedrooms", None),
        "bathrooms": getattr(prop, "bathrooms", None),
        "area_sqft": getattr(prop, "area_sqft", None),
        "is_available": getattr(prop, "is_available", True),
        "is_managed": getattr(prop, "is_managed", False),
        "management_status": management_status.value if management_status else None,
        "latitude": prop.latitude,
        "longitude": prop.longitude,
        "main_image_url": prop.main_image_url,
        "created_at": utc_iso(created_at),
    }


def serialize_property_full(prop: Property | Any, viewer: Any | None = None) -> dict:
    """Serialize a property object to full dict for MCP responses.

    Handles both SQLAlchemy models and Pydantic models. ``viewer`` is the caller
    (a user, a ``Viewer`` or None for anonymous). The owner's number reaches the
    owner and admins only; other viewers get the agent's or the company number.
    """
    # One path for ORM objects and Pydantic models, so both give the same wire shape.
    # The ORM read uses property_amenities; a Pydantic model carries amenities instead.
    prop = mask_owner_contact(prop, viewer)

    basic = serialize_property_basic(prop)

    available_from = getattr(prop, "available_from", None)
    updated_at = getattr(prop, "updated_at", None)

    amenities_data = []
    prop_amenities = (
        getattr(prop, "property_amenities", None) or getattr(prop, "amenities", None) or []
    )
    for a in prop_amenities:
        amenity_obj = getattr(a, "amenity", a)
        amenities_data.append(
            {
                "id": getattr(amenity_obj, "id", None),
                "name": getattr(amenity_obj, "title", None),
                "icon": getattr(amenity_obj, "icon", None),
                "category": getattr(amenity_obj, "category", None),
            }
        )

    basic.update(
        {
            # owner_contact arrives masked for non-owner viewers (visibility.mask_owner_contact).
            "owner_phone": getattr(prop, "owner_contact", None),
            "furnished_status": getattr(prop, "furnishing_level", None),
            "age_years": getattr(prop, "age_of_property", None),
            "description": prop.description,
            "sub_locality": getattr(prop, "sub_locality", None),
            "landmark": getattr(prop, "landmark", None),
            "pincode": getattr(prop, "pincode", None),
            "state": getattr(prop, "state", None),
            "country": getattr(prop, "country", None),
            "price_per_sqft": _money(getattr(prop, "price_per_sqft", None)),
            "security_deposit": _money(getattr(prop, "security_deposit", None)),
            "maintenance_charges": _money(getattr(prop, "maintenance_charges", None)),
            "balconies": getattr(prop, "balconies", None),
            "parking_spaces": getattr(prop, "parking_spaces", None),
            "floor_number": getattr(prop, "floor_number", None),
            "total_floors": getattr(prop, "total_floors", None),
            "max_occupancy": getattr(prop, "max_occupancy", None),
            "age_of_property": getattr(prop, "age_of_property", None),
            "virtual_tour_url": getattr(prop, "virtual_tour_url", None),
            "video_tour_url": getattr(prop, "video_tour_url", None),
            "features": getattr(prop, "features", None),
            "tags": getattr(prop, "tags", None),
            "available_from": utc_iso(available_from),
            "minimum_stay_days": getattr(prop, "minimum_stay_days", None),
            "owner_name": getattr(prop, "owner_name", None),
            "builder_name": getattr(prop, "builder_name", None),
            "view_count": getattr(prop, "view_count", 0),
            "like_count": getattr(prop, "like_count", 0),
            "payment_due_day": getattr(prop, "payment_due_day", None),
            "grace_period_days": getattr(prop, "grace_period_days", None),
            "images": [
                {"url": i.image_url, "caption": getattr(i, "caption", None)}
                for i in (getattr(prop, "images", None) or [])
            ],
            "amenities": amenities_data,
            "updated_at": utc_iso(updated_at),
        }
    )
    return basic


def serialize_rent_payment(payment: RentPayment) -> dict:
    """One rent payment, from the ORM row. Every MCP and agent rent output uses this shape."""
    method = payment.payment_method
    status = payment.status
    return {
        "id": payment.id,
        "charge_id": payment.charge_id,
        "lease_id": payment.lease_id,
        "property_id": payment.property_id,
        "amount_paid": _money(payment.amount_paid),
        "paid_at": utc_iso(payment.paid_at),
        "payment_method": getattr(method, "value", method),
        "status": getattr(status, "value", status),
        "reference": payment.reference,
        "notes": payment.notes,
        "created_at": utc_iso(payment.created_at),
    }


def serialize_booking(booking: Booking) -> dict:
    """Serialize a booking object for MCP responses."""
    booking_status = getattr(booking, "booking_status", None)
    payment_status = getattr(booking, "payment_status", None)
    cancellation_date = getattr(booking, "cancellation_date", None)
    created_at = getattr(booking, "created_at", None)

    # Nested property is only present when the caller eager-loaded the
    # relationship (e.g. via selectinload). Check the unloaded set so a bare
    # Booking never triggers an async lazy-load (MissingGreenlet). raiseerr=False
    # returns None for non-mapped objects (e.g. test doubles) instead of raising.
    property_data = None
    state = inspect(booking, raiseerr=False)
    if state is not None and "property" not in state.unloaded:
        loaded_property = booking.property
        if loaded_property is not None:
            property_data = serialize_property_basic(loaded_property)

    return {
        "id": booking.id,
        "booking_reference": getattr(booking, "booking_reference", None),
        "property_id": booking.property_id,
        "property": property_data,
        # Aliases so the shared VisitList/VisitScheduler widgets (which read
        # `status` / `scheduled_date`) can render bookings and visits alike.
        "status": booking_status.value if booking_status else None,
        "scheduled_date": utc_iso(booking.check_in_date),
        "user_id": booking.user_id,
        "check_in_date": utc_iso(booking.check_in_date),
        "check_out_date": utc_iso(booking.check_out_date),
        "guests": getattr(booking, "guests", None),
        "nights": getattr(booking, "nights", None),
        "base_amount": float(getattr(booking, "base_amount", 0) or 0),
        "taxes_amount": float(getattr(booking, "taxes_amount", 0) or 0),
        "service_charges": float(getattr(booking, "service_charges", 0) or 0),
        "discount_amount": float(getattr(booking, "discount_amount", 0) or 0),
        "total_amount": float(getattr(booking, "total_amount", 0) or 0),
        "booking_status": booking_status.value if booking_status else None,
        "payment_status": payment_status.value if payment_status else None,
        "payment_method": getattr(booking, "payment_method", None),
        "special_requests": getattr(booking, "special_requests", None),
        "cancellation_reason": getattr(booking, "cancellation_reason", None),
        "cancellation_date": utc_iso(cancellation_date),
        "created_at": utc_iso(created_at),
    }


def _loaded(obj: Any, name: str) -> Any:
    """A relationship value when it is loaded, else None. Never triggers a lazy load."""
    try:
        state = inspect(obj)
    except NoInspectionAvailable:  # plain objects and test doubles
        return getattr(obj, name, None)
    if name in state.unloaded:
        return None
    return getattr(obj, name, None)


def serialize_lease(lease: Lease, viewer: Any | None) -> dict:
    """The one lease wire shape, used by every MCP and agent lease tool.

    ``property`` and ``tenant`` are set when the query loaded them (selectinload).
    ``viewer`` is the caller (a user, a ``Viewer`` or None). The tenant is a PublicUserRef
    (id, display_name, avatar_url). phone and email are added only for the lease owner,
    admins and the tenant themself (app.services.visibility.mask_user_ref).
    """
    start_date = getattr(lease, "start_date", None)
    end_date = getattr(lease, "end_date", None)
    status = getattr(lease, "status", None)
    created_at = getattr(lease, "created_at", None)
    updated_at = getattr(lease, "updated_at", None)

    prop = _loaded(lease, "property")
    tenant = _loaded(lease, "tenant_user")
    property_data = None
    if prop is not None:
        images = _loaded(prop, "images") or []
        property_data = {
            "id": prop.id,
            "title": prop.title,
            "locality": prop.locality,
            "city": prop.city,
            "full_address": prop.full_address,
            "main_image_url": images[0].image_url if images else None,
        }
    tenant_data = mask_user_ref(tenant, viewer, owner_id=getattr(lease, "owner_id", None))

    return {
        "id": lease.id,
        "property_id": lease.property_id,
        "property": property_data,
        "owner_id": getattr(lease, "owner_id", None),
        "tenant_user_id": getattr(lease, "tenant_user_id", None),
        "tenant": tenant_data,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "monthly_rent": _money(getattr(lease, "monthly_rent", 0) or 0),
        "security_deposit": _money(getattr(lease, "security_deposit", 0) or 0),
        "status": status.value if status else None,
        "payment_due_day": getattr(lease, "payment_due_day", None),
        "grace_period_days": getattr(lease, "grace_period_days", None),
        "late_fee_amount": _money(getattr(lease, "late_fee_amount", None)),
        "late_fee_percentage": getattr(lease, "late_fee_percentage", None),
        "terms": getattr(lease, "lease_terms", None),
        "notes": getattr(lease, "special_clauses", None),
        "created_at": utc_iso(created_at),
        "updated_at": utc_iso(updated_at),
    }


def serialize_maintenance_request(req: MaintenanceRequest) -> dict:
    """Serialize a maintenance request for MCP responses."""
    category = getattr(req, "category", None)
    category_value = (
        category.value if category is not None and hasattr(category, "value") else category
    )

    urgency = getattr(req, "urgency", None)
    urgency_value = urgency.value if urgency is not None and hasattr(urgency, "value") else urgency

    # Widget expects priority values: low|medium|high|urgent.
    # Our DB enum uses urgency: low|medium|high|emergency.
    priority_value = "urgent" if urgency_value == "emergency" else urgency_value

    request_status = getattr(req, "request_status", None)
    request_status_value = (
        request_status.value
        if request_status is not None and hasattr(request_status, "value")
        else request_status
    )

    work_order_status = getattr(req, "work_order_status", None)
    work_order_status_value = (
        work_order_status.value
        if work_order_status is not None and hasattr(work_order_status, "value")
        else work_order_status
    )

    scheduled_for = getattr(req, "scheduled_for", None)
    completed_at = getattr(req, "completed_at", None)
    estimated_cost = getattr(req, "estimated_cost", None)
    actual_cost = getattr(req, "actual_cost", None)
    created_at = getattr(req, "created_at", None)
    updated_at = getattr(req, "updated_at", None)

    # Best-effort mapping to widget status values:
    # open|in_progress|scheduled|completed|cancelled
    if work_order_status_value == "cancelled":
        status_value = "cancelled"
    elif completed_at is not None or request_status_value in ("resolved", "closed"):
        status_value = "completed"
    elif scheduled_for is not None:
        status_value = "scheduled"
    elif work_order_status_value == "in_progress":
        status_value = "in_progress"
    else:
        status_value = "open"

    return {
        "id": req.id,
        "property_id": getattr(req, "property_id", None),
        "lease_id": getattr(req, "lease_id", None),
        "reported_by_user_id": getattr(req, "tenant_user_id", None),
        "tenant_user_id": getattr(req, "tenant_user_id", None),
        "title": getattr(req, "title", None),
        "description": getattr(req, "description", None),
        "category": category_value,
        "priority": priority_value,
        "status": status_value,
        "request_status": request_status_value,
        "work_order_status": work_order_status_value,
        "estimated_cost": float(estimated_cost or 0) if estimated_cost else None,
        "actual_cost": float(actual_cost or 0) if actual_cost else None,
        "scheduled_date": utc_iso(scheduled_for),
        "completed_at": utc_iso(completed_at),
        "vendor_name": getattr(req, "vendor_name", None),
        "notes": getattr(req, "completion_notes", None),
        "created_at": utc_iso(created_at),
        "updated_at": utc_iso(updated_at),
    }
