from supabase import Client
from typing import Optional, Dict, Any
from app.repositories.user import UserRepository
from app.schemas.user import UserUpdate, User as UserSchema
from app.db.types import UserDB
from app.core.logging import get_logger

logger = get_logger(__name__)

def _parse_user_db_to_schema(user_db: Optional[UserDB]) -> Optional[UserSchema]:
    """Parse UserDB dict to Pydantic User schema"""
    if not user_db:
        return None
    
    # Convert the UserDB dict to User schema, handling any type conversions
    user_data = dict(user_db)
    
    # Handle date_of_birth conversion if it's a string
    if user_data.get("date_of_birth") and isinstance(user_data["date_of_birth"], str):
        from datetime import datetime
        try:
            user_data["date_of_birth"] = datetime.fromisoformat(user_data["date_of_birth"]).date()
        except Exception as e:
            logger.warning("Failed to parse date_of_birth", extra={"user_id": user_data.get("id"), "error": str(e)})
            user_data["date_of_birth"] = None
    
    return UserSchema.model_validate(user_data)

async def get_user_by_email(supabase: Client, email: str) -> Optional[UserSchema]:
    repo = UserRepository(supabase)
    user_db = await repo.get_by_email(email)
    return _parse_user_db_to_schema(user_db)

async def get_user_by_id(supabase: Client, user_id: int) -> Optional[UserSchema]:
    repo = UserRepository(supabase)
    user_db = await repo.get_by_id(user_id)
    return _parse_user_db_to_schema(user_db)

async def get_user_by_supabase_id(supabase: Client, supabase_user_id: str) -> Optional[UserSchema]:
    repo = UserRepository(supabase)
    user_db = await repo.get_by_supabase_id(supabase_user_id)
    return _parse_user_db_to_schema(user_db)

async def create_user_from_supabase(supabase: Client, supabase_user_data: Dict[str, Any]) -> UserSchema:
    """Create user in our database after Supabase authentication"""
    repo = UserRepository(supabase)
    user_db = await repo.create_from_supabase(supabase_user_data)
    return _parse_user_db_to_schema(user_db)

async def get_or_create_user_from_supabase(supabase: Client, supabase_user_data: Dict[str, Any]) -> UserSchema:
    """Get existing user or create new one from Supabase data"""
    repo = UserRepository(supabase)
    user_db = await repo.get_or_create_from_supabase(supabase_user_data)
    return _parse_user_db_to_schema(user_db)

async def update_user(supabase: Client, user_id: int, user_update: UserUpdate) -> Optional[UserSchema]:
    repo = UserRepository(supabase)
    user_db = await repo.update_user(user_id, user_update)
    return _parse_user_db_to_schema(user_db)

async def update_user_preferences(supabase: Client, user_id: int, preferences: Dict[str, Any]) -> Optional[UserSchema]:
    repo = UserRepository(supabase)
    user_db = await repo.update_preferences(user_id, preferences)
    return _parse_user_db_to_schema(user_db)

async def update_user_location(supabase: Client, user_id: int, latitude: float, longitude: float) -> Optional[UserSchema]:
    repo = UserRepository(supabase)
    user_db = await repo.update_location(user_id, latitude, longitude)
    return _parse_user_db_to_schema(user_db)

