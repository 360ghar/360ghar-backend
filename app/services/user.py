from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate, UserUpdate

async def get_user_by_email(db: AsyncSession, email: str):
    repo = UserRepository(db)
    return await repo.get_by_email(email)

async def get_user_by_id(db: AsyncSession, user_id: int):
    repo = UserRepository(db)
    return await repo.get(user_id)

async def get_user_by_supabase_id(db: AsyncSession, supabase_user_id: str):
    repo = UserRepository(db)
    return await repo.get_by_supabase_id(supabase_user_id)

async def create_user_from_supabase(db: AsyncSession, supabase_user_data: Dict[str, Any]):
    """Create user in our database after Supabase authentication"""
    repo = UserRepository(db)
    return await repo.create_from_supabase(supabase_user_data)

async def get_or_create_user_from_supabase(db: AsyncSession, supabase_user_data: Dict[str, Any]):
    """Get existing user or create new one from Supabase data"""
    repo = UserRepository(db)
    return await repo.get_or_create_from_supabase(supabase_user_data)

async def update_user(db: AsyncSession, user_id: int, user_update: UserUpdate):
    repo = UserRepository(db)
    return await repo.update_user(user_id, user_update)

async def update_user_preferences(db: AsyncSession, user_id: int, preferences: dict):
    repo = UserRepository(db)
    return await repo.update_preferences(user_id, preferences)

async def update_user_location(db: AsyncSession, user_id: int, latitude: str, longitude: str):
    repo = UserRepository(db)
    return await repo.update_location(user_id, latitude, longitude)

async def deactivate_user(db: AsyncSession, user_id: int):
    repo = UserRepository(db)
    return await repo.deactivate(user_id)

async def verify_user(db: AsyncSession, user_id: int):
    repo = UserRepository(db)
    return await repo.verify(user_id)