from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.booking import (
    Booking,
    BookingAvailability,
    BookingCancel,
    BookingCreate,
    BookingPayment,
    BookingReview,
    BookingUpdate,
)
from app.schemas.common import MessageResponse
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.services.booking import (
    add_review,
    calculate_pricing,
    cancel_booking,
    check_availability,
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

router = APIRouter()


@router.post(
    "",
    response_model=Booking,
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
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Create booking."""
    return await create_booking(db, current_user.id, booking)

@router.get("", response_model=CursorPage[Booking], summary="List my bookings")
async def get_my_bookings(
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List my bookings."""
    rows, next_payload, total = await get_user_bookings(
        db, current_user.id,
        cursor_payload=page.decoded(), limit=page.limit, with_total=page.include_total,
    )
    return build_cursor_page(
        [Booking.model_validate(r, from_attributes=True) for r in rows],
        limit=page.limit, next_payload=next_payload, total=total,
    )

@router.get("/upcoming", response_model=CursorPage[Booking], summary="List upcoming bookings")
async def get_upcoming_bookings(
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List upcoming bookings."""
    rows, next_payload, total = await get_user_upcoming_bookings(
        db, current_user.id,
        cursor_payload=page.decoded(), limit=page.limit, with_total=page.include_total,
    )
    return build_cursor_page(
        [Booking.model_validate(r, from_attributes=True) for r in rows],
        limit=page.limit, next_payload=next_payload, total=total,
    )

@router.get("/past", response_model=CursorPage[Booking], summary="List past bookings")
async def get_past_bookings(
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List past bookings."""
    rows, next_payload, total = await get_user_past_bookings(
        db, current_user.id,
        cursor_payload=page.decoded(), limit=page.limit, with_total=page.include_total,
    )
    return build_cursor_page(
        [Booking.model_validate(r, from_attributes=True) for r in rows],
        limit=page.limit, next_payload=next_payload, total=total,
    )

@router.post("/check-availability", summary="Check booking availability")
async def check_booking_availability(
    availability_check: BookingAvailability,
    db: AsyncSession = Depends(get_db)
):
    """Check booking availability."""
    return await check_availability(
        db,
        availability_check.property_id,
        availability_check.check_in_date.strftime('%Y-%m-%d'),
        availability_check.check_out_date.strftime('%Y-%m-%d'),
        availability_check.guests
    )

@router.post("/calculate-pricing", summary="Calculate booking pricing")
async def calculate_booking_pricing(
    pricing_request: BookingAvailability,
    db: AsyncSession = Depends(get_db)
):
    """Calculate booking pricing."""
    return await calculate_pricing(
        db,
        pricing_request.property_id,
        pricing_request.check_in_date,
        pricing_request.check_out_date,
        pricing_request.guests
    )

@router.get("/all", response_model=CursorPage[Booking], summary="List all bookings")
async def list_all_bookings(
    page: CursorParams = Depends(),
    status: str | None = Query(None),
    agent_id: int | None = Query(None, description="Admin only: filter by agent id"),
    property_id: int | None = Query(None),
    user_id: int | None = Query(None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Global bookings listing. Admins see all; agents see their managed users/properties."""
    effective_agent_id = None
    if current_user.role == UserRole.admin.value:
        effective_agent_id = agent_id
    elif current_user.role == UserRole.agent.value:
        effective_agent_id = current_user.agent_id
        if effective_agent_id is None:
            return build_cursor_page([], limit=page.limit, next_payload=None, total=0)
    else:
        raise HTTPException(status_code=403, detail="Access denied")

    rows, next_payload, total = await get_all_bookings(
        db,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
        status=status,
        filter_agent_id=effective_agent_id,
        property_id=property_id,
        user_id=user_id,
    )
    return build_cursor_page(
        [Booking.model_validate(r, from_attributes=True) for r in rows],
        limit=page.limit, next_payload=next_payload, total=total,
    )

@router.get("/{booking_id}", response_model=Booking, summary="Get booking details")
async def get_booking_details(
    booking_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get booking details."""
    booking = await get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not await can_access_booking(db, actor=current_user, booking_user_id=booking.user_id, booking_property_id=booking.property_id):
        raise HTTPException(status_code=403, detail="Access denied")

    return booking

@router.put("/{booking_id}", response_model=Booking, summary="Update booking")
async def update_booking_details(
    booking_id: int,
    booking_update: BookingUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update booking."""
    booking = await get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not await can_access_booking(db, actor=current_user, booking_user_id=booking.user_id, booking_property_id=booking.property_id):
        raise HTTPException(status_code=403, detail="Access denied")

    return await update_booking(db, booking_id, booking_update)

@router.post("/cancel", response_model=MessageResponse, summary="Cancel booking")
async def cancel_booking_request(
    cancel_data: BookingCancel,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel booking."""
    booking = await get_booking(db, cancel_data.booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not await can_access_booking(db, actor=current_user, booking_user_id=booking.user_id, booking_property_id=booking.property_id):
        raise HTTPException(status_code=403, detail="Access denied")

    success = await cancel_booking(db, cancel_data.booking_id, cancel_data.reason)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to cancel booking")

    return MessageResponse(message="Booking cancelled successfully")

@router.post("/payment", response_model=MessageResponse, summary="Process booking payment")
async def process_booking_payment(
    payment_data: BookingPayment,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Process booking payment."""
    booking = await get_booking(db, payment_data.booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not await can_access_booking(db, actor=current_user, booking_user_id=booking.user_id, booking_property_id=booking.property_id):
        raise HTTPException(status_code=403, detail="Access denied")

    success = await process_payment(db, payment_data)
    if not success:
        raise HTTPException(status_code=400, detail="Payment processing failed")

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

    return MessageResponse(message="Payment processed successfully")

@router.post("/review", response_model=MessageResponse, summary="Add booking review")
async def add_booking_review(
    review_data: BookingReview,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Add booking review."""
    booking = await get_booking(db, review_data.booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not await can_access_booking(db, actor=current_user, booking_user_id=booking.user_id, booking_property_id=booking.property_id):
        raise HTTPException(status_code=403, detail="Access denied")

    success = await add_review(db, review_data)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to add review")

    return MessageResponse(message="Review added successfully")
