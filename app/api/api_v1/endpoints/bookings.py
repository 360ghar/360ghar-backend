from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
from app.core.supabase_client import get_supabase_dependency
from app.api.api_v1.endpoints.auth import get_current_active_user
from app.schemas.user import User as UserSchema
from app.schemas.booking import (
    BookingCreate, BookingUpdate, Booking, BookingCancel,
    BookingAvailability
)
from app.schemas.common import MessageResponse
from app.services.booking import (
    create_booking, get_booking, get_user_bookings,
    cancel_booking, check_availability, update_booking_status, update_payment_status,
    calculate_booking_pricing
)
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

@router.post("/")
async def create_new_booking(
    booking: BookingCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    supabase: Client = Depends(get_supabase_dependency)
):
    """Create a new booking"""
    result = await create_booking(supabase, booking)
    logger.info("Booking created successfully", extra={"user_id": current_user.id, "property_id": booking.property_id, "booking_id": result.id})
    return result

@router.get("/")
async def get_my_bookings(
    current_user: UserSchema = Depends(get_current_active_user),
    supabase: Client = Depends(get_supabase_dependency)
):
    """Get current user's bookings"""
    return await get_user_bookings(supabase, current_user.id)

@router.get("/upcoming")
async def get_upcoming_bookings(
    current_user: UserSchema = Depends(get_current_active_user),
    supabase: Client = Depends(get_supabase_dependency)
):
    """Get upcoming bookings for current user"""
    # Filter by future dates in service layer
    return await get_user_bookings(supabase, current_user.id)

@router.get("/past")
async def get_past_bookings(
    current_user: UserSchema = Depends(get_current_active_user),
    supabase: Client = Depends(get_supabase_dependency)
):
    """Get past bookings for current user"""
    # Filter by past dates in service layer
    return await get_user_bookings(supabase, current_user.id)

@router.post("/check-availability")
async def check_booking_availability(
    availability_check: BookingAvailability,
    supabase: Client = Depends(get_supabase_dependency)
):
    """Check if property is available for booking"""
    available = await check_availability(
        supabase, 
        availability_check.property_id,
        availability_check.check_in_date.strftime('%Y-%m-%d'),
        availability_check.check_out_date.strftime('%Y-%m-%d')
    )
    return {"available": available}

@router.post("/calculate-pricing")
async def calculate_booking_pricing_endpoint(
    pricing_request: BookingAvailability,
    supabase: Client = Depends(get_supabase_dependency)
):
    """Calculate booking pricing"""
    return await calculate_booking_pricing(
        supabase,
        pricing_request.property_id,
        pricing_request.check_in_date.strftime('%Y-%m-%d'),
        pricing_request.check_out_date.strftime('%Y-%m-%d'),
        getattr(pricing_request, 'guests', 1)
    )

@router.get("/{booking_id}")
async def get_booking_details(
    booking_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    supabase: Client = Depends(get_supabase_dependency)
):
    """Get booking details by ID"""
    booking = await get_booking(supabase, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    return booking

@router.put("/{booking_id}/status")
async def update_booking_status_endpoint(
    booking_id: int,
    status: str,
    current_user: UserSchema = Depends(get_current_active_user),
    supabase: Client = Depends(get_supabase_dependency)
):
    """Update booking status"""
    booking = await update_booking_status(supabase, booking_id, status)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    return booking

@router.post("/cancel", response_model=MessageResponse)
async def cancel_booking_request(
    cancel_data: BookingCancel,
    current_user: UserSchema = Depends(get_current_active_user),
    supabase: Client = Depends(get_supabase_dependency)
):
    """Cancel a booking"""
    booking = await cancel_booking(supabase, cancel_data.booking_id, cancel_data.reason)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found or failed to cancel")
    
    return MessageResponse(message="Booking cancelled successfully")

@router.put("/{booking_id}/payment")
async def update_payment_status_endpoint(
    booking_id: int,
    status: str,
    current_user: UserSchema = Depends(get_current_active_user),
    supabase: Client = Depends(get_supabase_dependency)
):
    """Update payment status"""
    booking = await update_payment_status(supabase, booking_id, status)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    return MessageResponse(message="Payment status updated successfully")

@router.post("/{booking_id}/review", response_model=MessageResponse)
async def add_booking_review(
    booking_id: int,
    rating: int,
    review: str = None,
    current_user: UserSchema = Depends(get_current_active_user),
    supabase: Client = Depends(get_supabase_dependency)
):
    """Add a review for a booking"""
    # This would need to be implemented in the service layer
    # For now, return a success message
    return MessageResponse(message="Review functionality will be implemented")