from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.api.api_v1.endpoints.auth import get_current_active_user
from app.models.user import User
from app.schemas.booking import (
    BookingCreate, BookingUpdate, Booking, BookingList, BookingCancel,
    BookingPayment, BookingReview, BookingAvailability, BookingPricing
)
from app.schemas.common import MessageResponse
from app.services.booking import (
    create_booking, get_booking, get_user_bookings, update_booking,
    cancel_booking, process_payment, add_review, check_availability,
    calculate_pricing
)

router = APIRouter()

@router.post("/", response_model=Booking)
async def create_new_booking(
    booking: BookingCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    return await create_booking(db, current_user.id, booking)

@router.get("/", response_model=BookingList)
async def get_my_bookings(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    return await get_user_bookings(db, current_user.id)

@router.get("/upcoming")
async def get_upcoming_bookings(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    from app.services.booking import get_user_upcoming_bookings
    return await get_user_upcoming_bookings(db, current_user.id)

@router.get("/past")
async def get_past_bookings(
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    booking = await get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # Check if booking belongs to current user
    if booking.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return booking

@router.put("/{booking_id}", response_model=Booking)
async def update_booking_details(
    booking_id: int,
    booking_update: BookingUpdate,
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    booking = await get_booking(db, payment_data.booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # Check if booking belongs to current user
    if booking.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    success = await process_payment(db, payment_data)
    if not success:
        raise HTTPException(status_code=400, detail="Payment processing failed")
    
    return MessageResponse(message="Payment processed successfully")

@router.post("/review", response_model=MessageResponse)
async def add_booking_review(
    review_data: BookingReview,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    booking = await get_booking(db, review_data.booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # Check if booking belongs to current user
    if booking.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    success = await add_review(db, review_data)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to add review")
    
    return MessageResponse(message="Review added successfully")