from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.api.api_v1.dependencies.auth import get_current_active_user
from app.models.enums import UserRole
from app.schemas.user import User as UserSchema
from app.schemas.booking import (
    BookingCreate, BookingUpdate, Booking, BookingList, BookingCancel,
    BookingPayment, BookingReview, BookingAvailability, BookingPricing
)
from app.schemas.common import MessageResponse
from app.services.booking import (
    create_booking,
    get_booking,
    get_user_bookings,
    update_booking,
    cancel_booking,
    process_payment,
    add_review,
    check_availability,
    calculate_pricing,
    get_all_bookings,
)
from app.services.notification_dispatcher import dispatch_notification_to_user

router = APIRouter()


async def _agent_can_access_booking(
    current_user: UserSchema,
    booking: Booking,
    db: AsyncSession,
) -> bool:
    if current_user.role != UserRole.agent.value or current_user.agent_id is None:
        return False

    from app.models.properties import Property
    from app.models.users import User as UserModel

    booking_user = await db.get(UserModel, booking.user_id)
    property_obj = await db.get(Property, booking.property_id)
    owner = await db.get(UserModel, property_obj.owner_id) if property_obj else None

    return bool(
        (booking_user and booking_user.agent_id == current_user.agent_id)
        or (owner and owner.agent_id == current_user.agent_id)
    )


async def _can_access_booking(
    current_user: UserSchema,
    booking: Booking,
    db: AsyncSession,
) -> bool:
    if booking.user_id == current_user.id:
        return True
    if current_user.role == UserRole.admin.value:
        return True
    return await _agent_can_access_booking(current_user, booking, db)


@router.post("", response_model=Booking)
async def create_new_booking(
    booking: BookingCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    return await create_booking(db, current_user.id, booking)

@router.get("", response_model=BookingList)
async def get_my_bookings(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    return await get_user_bookings(db, current_user.id)

@router.get("/upcoming")
async def get_upcoming_bookings(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    from app.services.booking import get_user_upcoming_bookings
    return await get_user_upcoming_bookings(db, current_user.id)

@router.get("/past")
async def get_past_bookings(
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    from app.services.booking import get_user_past_bookings
    return await get_user_past_bookings(db, current_user.id)

@router.post("/check-availability")
async def check_booking_availability(
    availability_check: BookingAvailability,
    db: AsyncSession = Depends(get_db)
):
    return await check_availability(
        db, 
        availability_check.property_id,
        availability_check.check_in_date.strftime('%Y-%m-%d'),
        availability_check.check_out_date.strftime('%Y-%m-%d'),
        availability_check.guests
    )

@router.post("/calculate-pricing")
async def calculate_booking_pricing(
    pricing_request: BookingAvailability,
    db: AsyncSession = Depends(get_db)
):
    return await calculate_pricing(
        db,
        pricing_request.property_id,
        pricing_request.check_in_date,
        pricing_request.check_out_date,
        pricing_request.guests
    )

@router.get("/{booking_id}", response_model=Booking)
async def get_booking_details(
    booking_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    booking = await get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not await _can_access_booking(current_user, booking, db):
        raise HTTPException(status_code=403, detail="Access denied")

    return booking

@router.put("/{booking_id}", response_model=Booking)
async def update_booking_details(
    booking_id: int,
    booking_update: BookingUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    booking = await get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # Check if booking belongs to current user
    if booking.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return await update_booking(db, booking_id, booking_update)

@router.post("/cancel", response_model=MessageResponse)
async def cancel_booking_request(
    cancel_data: BookingCancel,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    booking = await get_booking(db, cancel_data.booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # Check if booking belongs to current user
    if booking.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    success = await cancel_booking(db, cancel_data.booking_id, cancel_data.reason)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to cancel booking")
    
    return MessageResponse(message="Booking cancelled successfully")

@router.post("/payment", response_model=MessageResponse)
async def process_booking_payment(
    payment_data: BookingPayment,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    booking = await get_booking(db, payment_data.booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not await _can_access_booking(current_user, booking, db):
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

@router.post("/review", response_model=MessageResponse)
async def add_booking_review(
    review_data: BookingReview,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    booking = await get_booking(db, review_data.booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not await _can_access_booking(current_user, booking, db):
        raise HTTPException(status_code=403, detail="Access denied")

    success = await add_review(db, review_data)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to add review")
    
    return MessageResponse(message="Review added successfully")


@router.get("/all", response_model=BookingList)
async def list_all_bookings(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    agent_id: int | None = Query(None, description="Admin only: filter by agent id"),
    property_id: int | None = Query(None),
    user_id: int | None = Query(None),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Global bookings listing. Admins see all; agents see their managed users/properties."""
    effective_agent_id = None
    if current_user.role == UserRole.admin.value:
        effective_agent_id = agent_id
    elif current_user.role == UserRole.agent.value:
        effective_agent_id = current_user.agent_id
        if effective_agent_id is None:
            return {"bookings": [], "total": 0, "page": page, "limit": limit, "total_pages": 0}
    else:
        raise HTTPException(status_code=403, detail="Access denied")

    return await get_all_bookings(
        db,
        page=page,
        limit=limit,
        status=status,
        filter_agent_id=effective_agent_id,
        property_id=property_id,
        user_id=user_id,
    )
