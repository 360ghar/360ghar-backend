from supabase import Client
from datetime import datetime, timedelta
from app.repositories.booking import BookingRepository
from app.schemas.booking import BookingCreate, BookingUpdate
from typing import Dict, Any, List, Optional

async def create_booking(supabase: Client, booking_data: BookingCreate):
    """Create a new booking"""
    booking_repo = BookingRepository(supabase)
    return await booking_repo.create_booking(booking_data)

async def get_booking(supabase: Client, booking_id: int):
    """Get booking by ID"""
    booking_repo = BookingRepository(supabase)
    return await booking_repo.get_by_id(booking_id)

async def get_booking_by_reference(supabase: Client, reference: str):
    """Get booking by reference number"""
    booking_repo = BookingRepository(supabase)
    return await booking_repo.get_booking_by_reference(reference)

async def get_user_bookings(supabase: Client, user_id: int, page: int = 1, limit: int = 20):
    """Get user's bookings"""
    booking_repo = BookingRepository(supabase)
    return await booking_repo.get_user_bookings(user_id, page, limit)

async def get_property_bookings(supabase: Client, property_id: int, page: int = 1, limit: int = 20):
    """Get property's bookings"""
    booking_repo = BookingRepository(supabase)
    return await booking_repo.get_property_bookings(property_id, page, limit)

async def check_availability(supabase: Client, property_id: int, check_in: str, check_out: str) -> bool:
    """Check if property is available for given dates"""
    booking_repo = BookingRepository(supabase)
    return await booking_repo.check_availability(property_id, check_in, check_out)

async def update_booking_status(supabase: Client, booking_id: int, status: str):
    """Update booking status"""
    booking_repo = BookingRepository(supabase)
    return await booking_repo.update_booking_status(booking_id, status)

async def update_payment_status(supabase: Client, booking_id: int, status: str):
    """Update payment status"""
    booking_repo = BookingRepository(supabase)
    return await booking_repo.update_payment_status(booking_id, status)

async def cancel_booking(supabase: Client, booking_id: int, reason: str):
    """Cancel a booking"""
    booking_repo = BookingRepository(supabase)
    return await booking_repo.cancel_booking(booking_id, reason)

async def calculate_booking_pricing(
    supabase: Client, 
    property_id: int, 
    check_in: str, 
    check_out: str, 
    guests: int = 1
) -> Dict[str, Any]:
    """Calculate booking pricing using database function"""
    booking_repo = BookingRepository(supabase)
    return await booking_repo.calculate_pricing(property_id, check_in, check_out, guests)