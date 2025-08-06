from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from app.repositories.booking import BookingRepository
from app.schemas.booking import BookingCreate, BookingUpdate, BookingPayment, BookingReview


async def create_booking(db: AsyncSession, user_id: int, booking: BookingCreate):
    booking_repo = BookingRepository(db)
    return await booking_repo.create_booking(user_id, booking)

async def get_booking(db: AsyncSession, booking_id: int):
    booking_repo = BookingRepository(db)
    return await booking_repo.get(booking_id)

async def get_user_bookings(db: AsyncSession, user_id: int):
    booking_repo = BookingRepository(db)
    return await booking_repo.get_user_bookings(user_id)

async def get_user_upcoming_bookings(db: AsyncSession, user_id: int):
    booking_repo = BookingRepository(db)
    return await booking_repo.get_user_upcoming_bookings(user_id)

async def get_user_past_bookings(db: AsyncSession, user_id: int):
    booking_repo = BookingRepository(db)
    return await booking_repo.get_user_past_bookings(user_id)

async def update_booking(db: AsyncSession, booking_id: int, booking_update: BookingUpdate):
    booking_repo = BookingRepository(db)
    return await booking_repo.update_booking(booking_id, booking_update)

async def cancel_booking(db: AsyncSession, booking_id: int, reason: str):
    booking_repo = BookingRepository(db)
    return await booking_repo.cancel_booking(booking_id, reason)

async def process_payment(db: AsyncSession, payment_data: BookingPayment):
    booking_repo = BookingRepository(db)
    return await booking_repo.process_payment(payment_data)

async def add_review(db: AsyncSession, review_data: BookingReview):
    booking_repo = BookingRepository(db)
    return await booking_repo.add_review(review_data)

async def check_availability(db: AsyncSession, property_id: int, check_in_date: str, check_out_date: str, guests: int):
    booking_repo = BookingRepository(db)
    return await booking_repo.check_availability(property_id, check_in_date, check_out_date, guests)

async def calculate_pricing(db: AsyncSession, property_id: int, check_in_date: datetime, check_out_date: datetime, guests: int):
    booking_repo = BookingRepository(db)
    return await booking_repo.calculate_pricing(property_id, check_in_date, check_out_date, guests)