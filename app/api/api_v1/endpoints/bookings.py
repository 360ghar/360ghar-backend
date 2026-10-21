from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_cached_active_user,
)
from app.core.database import get_db
from app.core.db_resilience import raise_read_service_unavailable
from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.enums import BookingStatus, PaymentStatus
from app.models.users import User
from app.schemas.base import PublicUserRef
from app.schemas.booking import (
    Booking,
    BookingAvailability,
    BookingCancel,
    BookingCreate,
    BookingOccupancyCheck,
    BookingOccupancyResult,
    BookingPayment,
    BookingPricing,
    BookingPropertySummary,
    BookingReview,
    BookingStaff,
    BookingUpdate,
)
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.services.auth_user_cache import AuthUserSnapshot
from app.services.booking import (
    add_review,
    calculate_pricing,
    cancel_booking,
    check_occupancy,
    create_booking,
    get_all_bookings,
    get_booking,
    get_user_bookings,
    get_user_past_bookings,
    get_user_upcoming_bookings,
    process_payment,
    update_booking,
)
from app.services.notification_dispatcher import dispatch_notification_to_user
from app.services.pm_authz import can_access_booking
from app.services.visibility import Viewer

router = APIRouter()

# Guest routes return Booking. Admins and agents get BookingStaff (adds internal_notes).
BookingOut = Booking | BookingStaff


def _property_summary(prop: Any) -> BookingPropertySummary | None:
    if prop is None:
        return None
    images = sorted(
        prop.images or [], key=lambda img: (not img.is_main_image, img.display_order or 0)
    )
    return BookingPropertySummary(
        id=prop.id,
        title=prop.title,
        city=prop.city,
        country=prop.country,
        cover_image_url=images[0].image_url if images else None,
    )


def _booking_out(booking: Any, viewer: Viewer) -> BookingOut:
    """Serialize a booking for the viewer. Only staff get internal_notes."""
    schema = BookingStaff if (viewer.is_admin or viewer.is_agent) else Booking
    fields: dict[str, Any] = {
        name: getattr(booking, name, None)
        for name in schema.model_fields
        if name not in ("property", "guest")
    }
    fields["property"] = _property_summary(booking.property)
    fields["guest"] = (
        PublicUserRef.model_validate(booking.user, from_attributes=True)
        if booking.user is not None
        else None
    )
    return schema.model_validate(fields)


def _bookings_out(rows, viewer: Viewer) -> list[BookingOut]:
    return [_booking_out(row, viewer) for row in rows]


async def _resolve_guest_id(db: AsyncSession, actor: User, requested_user_id: int | None) -> int:
    """Admins and agents may name the guest. Everyone else books for themselves."""
    viewer = Viewer.from_user(actor)
    if requested_user_id is None or not (viewer.is_admin or viewer.is_agent):
        return actor.id
    if await db.get(User, requested_user_id) is None:
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    return requested_user_id


async def _reload_out(db: AsyncSession, booking_id: int, viewer: Viewer) -> BookingOut:
    """Re-read a booking with its summary relations loaded, then serialize it."""
    fresh = await get_booking(db, booking_id)
    if fresh is None:
        raise NotFoundException(detail="Booking not found", error_code="BOOKING_NOT_FOUND")
    return _booking_out(fresh, viewer)


@router.post(
    "",
    response_model=BookingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create booking",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create": {
                            "value": {
                                "property_id": 1,
                                "check_in_date": "2026-07-01T12:00:00Z",
                                "check_out_date": "2026-07-05T11:00:00Z",
                                "guests": 2,
                                "primary_guest_name": "Rahul Sharma",
                                "primary_guest_phone": "+919876543210",
                                "primary_guest_email": "rahul@example.com",
                            }
                        },
                    }
                }
            }
        }
    },
)
async def create_new_booking(
    booking: BookingCreate,
    idempotency_key: str | None = Header(
        None,
        alias="Idempotency-Key",
        max_length=128,
        description=(
            "Repeat the same key to retry safely. A retry returns the first booking. "
            "A blank key gives 422."
        ),
    ),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create booking. A repeated Idempotency-Key from the same caller returns the first booking."""
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key:
            # A blank key would match every later blank-key booking and return the first one.
            raise ValidationException(
                detail="Idempotency-Key must not be blank.", error_code="INVALID_IDEMPOTENCY_KEY"
            )
    owner_id = await _resolve_guest_id(db, current_user, booking.user_id)
    created = await create_booking(
        db,
        owner_id,
        booking,
        created_by_id=current_user.id,
        idempotency_key=idempotency_key,
    )
    return await _reload_out(db, created.id, Viewer.from_user(current_user))


@router.get("", response_model=CursorPage[Booking], summary="List my bookings")
async def get_my_bookings(
    page: CursorParams = Depends(),
    status: BookingStatus | None = Query(None, description="Filter by booking status"),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List my bookings."""
    filters = {"status": status}
    cursor_payload = page.decoded(filters)
    try:
        rows, next_payload, total = await get_user_bookings(
            db,
            current_user.id,
            cursor_payload=cursor_payload,
            limit=page.limit,
            with_total=page.include_total,
            status=status,
        )
        return build_cursor_page(
            _bookings_out(rows, Viewer.from_user(current_user)),
            limit=page.limit,
            next_payload=next_payload,
            total=total,
            filters=filters,
        )
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="bookings_list",
            detail="Bookings are temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.get("/upcoming", response_model=CursorPage[Booking], summary="List upcoming bookings")
async def get_upcoming_bookings(
    page: CursorParams = Depends(),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List upcoming bookings."""
    filters: dict = {}
    cursor_payload = page.decoded(filters)
    try:
        rows, next_payload, total = await get_user_upcoming_bookings(
            db,
            current_user.id,
            cursor_payload=cursor_payload,
            limit=page.limit,
            with_total=page.include_total,
        )
        return build_cursor_page(
            _bookings_out(rows, Viewer.from_user(current_user)),
            limit=page.limit,
            next_payload=next_payload,
            total=total,
            filters=filters,
        )
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="bookings_upcoming",
            detail="Upcoming bookings are temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.get("/past", response_model=CursorPage[Booking], summary="List past bookings")
async def get_past_bookings(
    page: CursorParams = Depends(),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List past bookings."""
    filters: dict = {}
    cursor_payload = page.decoded(filters)
    try:
        rows, next_payload, total = await get_user_past_bookings(
            db,
            current_user.id,
            cursor_payload=cursor_payload,
            limit=page.limit,
            with_total=page.include_total,
        )
        return build_cursor_page(
            _bookings_out(rows, Viewer.from_user(current_user)),
            limit=page.limit,
            next_payload=next_payload,
            total=total,
            filters=filters,
        )
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="bookings_past",
            detail="Past bookings are temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.post(
    "/check-availability",
    response_model=BookingOccupancyResult,
    summary="Check guest count against property capacity",
)
async def check_booking_availability(
    occupancy_check: BookingOccupancyCheck, db: AsyncSession = Depends(get_db)
):
    """Check the guest count against the property's max occupancy.

    Dates are not checked: overlapping bookings are allowed.
    """
    result = await check_occupancy(db, occupancy_check.property_id, occupancy_check.guests)
    if result.get("error_code") == "PROPERTY_NOT_FOUND":
        raise NotFoundException(detail="Property not found", error_code="PROPERTY_NOT_FOUND")
    return BookingOccupancyResult(
        occupancy_ok=result["available"],
        reason=result.get("reason"),
        max_occupancy=result.get("max_occupancy"),
    )


@router.post(
    "/calculate-pricing", response_model=BookingPricing, summary="Calculate booking pricing"
)
async def calculate_booking_pricing(
    pricing_request: BookingAvailability, db: AsyncSession = Depends(get_db)
):
    """Calculate booking pricing. A pricing failure is a 4xx error with a code."""
    pricing = await calculate_pricing(
        db,
        pricing_request.property_id,
        pricing_request.check_in_date,
        pricing_request.check_out_date,
        pricing_request.guests,
    )
    if "error" in pricing:
        code = pricing.get("error_code", "PRICING_UNAVAILABLE")
        if code == "PROPERTY_NOT_FOUND":
            raise NotFoundException(detail=pricing["error"], error_code=code)
        raise BadRequestException(detail=pricing["error"], error_code=code)
    return BookingPricing(**{name: pricing[name] for name in BookingPricing.model_fields})


@router.get("/all", response_model=CursorPage[BookingStaff], summary="List all bookings")
async def list_all_bookings(
    page: CursorParams = Depends(),
    status: BookingStatus | None = Query(None),
    payment_status: PaymentStatus | None = Query(None),
    agent_id: int | None = Query(None, description="Admin only: filter by agent id"),
    property_id: int | None = Query(None),
    user_id: int | None = Query(None),
    q: str | None = Query(
        None,
        max_length=200,
        description="Search the booking reference, primary guest name or email, or property title",
    ),
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Global bookings listing. Admins see all; agents see their managed users/properties."""
    viewer = Viewer.from_user(current_user)
    effective_agent_id = None
    if viewer.is_admin:
        effective_agent_id = agent_id
    elif viewer.is_agent:
        effective_agent_id = current_user.agent_id
    else:
        raise HTTPException(status_code=403, detail="Access denied")

    filters = {
        "status": status,
        "payment_status": payment_status,
        "agent_id": agent_id,
        "property_id": property_id,
        "user_id": user_id,
        "q": q,
    }
    cursor_payload = page.decoded(filters)
    if viewer.is_agent and effective_agent_id is None:
        return build_cursor_page(
            [],
            limit=page.limit,
            next_payload=None,
            total=0 if page.include_total else None,
            filters=filters,
        )

    try:
        rows, next_payload, total = await get_all_bookings(
            db,
            cursor_payload=cursor_payload,
            limit=page.limit,
            with_total=page.include_total,
            status=status,
            payment_status=payment_status,
            filter_agent_id=effective_agent_id,
            property_id=property_id,
            user_id=user_id,
            q=q,
        )
        return build_cursor_page(
            _bookings_out(rows, viewer),
            limit=page.limit,
            next_payload=next_payload,
            total=total,
            filters=filters,
        )
    except Exception as exc:
        raise_read_service_unavailable(
            exc,
            endpoint="bookings_all",
            detail="Bookings are temporarily unavailable. Please retry shortly.",
            extra={"user": current_user.id},
        )
        raise


@router.get("/{booking_id}", response_model=BookingOut, summary="Get booking details")
async def get_booking_details(
    booking_id: int,
    current_user: AuthUserSnapshot = Depends(get_current_cached_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get booking details."""
    booking = await get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not await can_access_booking(
        db,
        actor=current_user,
        booking_user_id=booking.user_id,
        booking_property_id=booking.property_id,
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    return _booking_out(booking, Viewer.from_user(current_user))


@router.put("/{booking_id}", response_model=BookingOut, summary="Update booking")
async def update_booking_details(
    booking_id: int,
    booking_update: BookingUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update booking. Only the fields sent are changed. Only staff may set internal_notes."""
    booking = await get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not await can_access_booking(
        db,
        actor=current_user,
        booking_user_id=booking.user_id,
        booking_property_id=booking.property_id,
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    viewer = Viewer.from_user(current_user)
    if "internal_notes" in booking_update.model_fields_set and not (
        viewer.is_admin or viewer.is_agent
    ):
        raise ForbiddenException(
            detail="Only admins and agents may set internal notes", error_code="FORBIDDEN"
        )

    await update_booking(db, booking_id, booking_update)
    return await _reload_out(db, booking_id, viewer)


@router.post("/cancel", response_model=BookingOut, summary="Cancel booking")
async def cancel_booking_request(
    cancel_data: BookingCancel,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel booking. Returns the cancelled booking."""
    booking = await get_booking(db, cancel_data.booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not await can_access_booking(
        db,
        actor=current_user,
        booking_user_id=booking.user_id,
        booking_property_id=booking.property_id,
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    success = await cancel_booking(db, cancel_data.booking_id, cancel_data.reason)
    if not success:
        raise BadRequestException(
            detail="Booking cannot be cancelled", error_code="BOOKING_NOT_CANCELLABLE"
        )

    return await _reload_out(db, cancel_data.booking_id, Viewer.from_user(current_user))


@router.post("/payment", response_model=BookingOut, summary="Record booking payment (admin only)")
async def process_booking_payment(
    payment_data: BookingPayment,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a manual booking payment. Admins only.

    The payment is recorded without a payment-gateway check.
    """
    viewer = Viewer.from_user(current_user)
    if not viewer.is_admin:
        raise HTTPException(
            status_code=403,
            detail="This endpoint is restricted to admins.",
        )

    booking = await get_booking(db, payment_data.booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not await can_access_booking(
        db,
        actor=current_user,
        booking_user_id=booking.user_id,
        booking_property_id=booking.property_id,
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    success = await process_payment(db, payment_data)
    if not success:
        raise BadRequestException(detail="Payment processing failed", error_code="PAYMENT_FAILED")

    # Send booking confirmation notification via multi-channel dispatcher
    try:
        await dispatch_notification_to_user(
            db,
            user_db_id=booking.user_id,
            type_key="booking_confirmed",
            title="Booking confirmed",
            body=f"Your booking {booking.booking_reference} has been confirmed.",
            data={
                "booking_id": str(booking.id),
                "booking_reference": booking.booking_reference,
                "property_id": str(booking.property_id),
            },
        )
    except Exception:
        # Notification failures should not break payment flow
        pass

    return await _reload_out(db, payment_data.booking_id, viewer)


@router.post("/review", response_model=BookingOut, summary="Add booking review")
async def add_booking_review(
    review_data: BookingReview,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Add booking review. Only the guest who made the booking may submit a review,
    and only after the stay is completed or checked-out."""
    booking = await get_booking(db, review_data.booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    success = await add_review(db, review_data, actor_id=current_user.id)
    if not success:
        raise BadRequestException(detail="Failed to add review", error_code="REVIEW_NOT_ALLOWED")

    return await _reload_out(db, review_data.booking_id, Viewer.from_user(current_user))
