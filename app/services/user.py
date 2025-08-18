from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, Dict, Any
from app.models.models import User
from app.schemas.user import UserUpdate
from app.core.logging import get_logger

logger = get_logger(__name__)

async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    logger.debug(f"Fetching user by email: {email}")
    try:
        stmt = select(User).where(User.email == email)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            logger.debug(f"User found with ID {user.id}")
        else:
            logger.debug(f"No user found with email {email}")
        return user
    except Exception as e:
        logger.error(f"Failed to fetch user by email {email}: {str(e)}", exc_info=True)
        raise

async def get_user_by_supabase_id(db: AsyncSession, supabase_user_id: str) -> Optional[User]:
    logger.debug(f"Fetching user by Supabase ID: {supabase_user_id}")
    try:
        stmt = select(User).where(User.supabase_user_id == supabase_user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            logger.debug(f"User found with ID {user.id}")
        else:
            logger.debug(f"No user found with Supabase ID {supabase_user_id}")
        return user
    except Exception as e:
        logger.error(f"Failed to fetch user by Supabase ID {supabase_user_id}: {str(e)}", exc_info=True)
        raise

async def get_or_create_user_from_supabase(db: AsyncSession, supabase_user_data: Dict[str, Any]) -> User:
    """Get or create user from Supabase auth data"""
    logger.info(f"Getting or creating user from Supabase data for user {supabase_user_data['id']}")
    
    try:
        user = await get_user_by_supabase_id(db, supabase_user_data["id"])
        
        if not user:
            user = await get_user_by_email(db, supabase_user_data["email"])
            
            if user:
                # Update with Supabase ID
                logger.info(f"Updating existing user {user.id} with Supabase ID")
                user.supabase_user_id = supabase_user_data["id"]
            else:
                # Create new user
                logger.info(f"Creating new user from Supabase data: {supabase_user_data['email']}")
                user = User(
                    supabase_user_id=supabase_user_data["id"],
                    email=supabase_user_data["email"],
                    full_name=supabase_user_data.get("user_metadata", {}).get("full_name"),
                    phone=supabase_user_data.get("phone"),
                    is_active=True,
                    is_verified=supabase_user_data.get("email_verified", False)
                )
                db.add(user)
            
            await db.flush()
            await db.refresh(user)
            logger.info(f"User {'updated' if user.supabase_user_id else 'created'} with ID {user.id}")
        else:
            logger.debug(f"User already exists with ID {user.id}")
        
        return user
    except Exception as e:
        logger.error(f"Failed to get or create user from Supabase: {str(e)}", exc_info=True)
        raise

async def update_user(db: AsyncSession, user_id: int, user_update: UserUpdate) -> Optional[User]:
    logger.info(f"Updating user {user_id}")
    
    try:
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if user:
            update_data = user_update.model_dump(exclude_unset=True)
            logger.debug(f"Updating user {user_id} with fields: {list(update_data.keys())}")
            
            for field, value in update_data.items():
                setattr(user, field, value)
            
            await db.flush()
            await db.refresh(user)
            logger.info(f"User {user_id} updated successfully")
        else:
            logger.warning(f"User {user_id} not found for update")
        
        return user
    except Exception as e:
        logger.error(f"Failed to update user {user_id}: {str(e)}", exc_info=True)
        raise

async def update_user_preferences(db: AsyncSession, user_id: int, preferences: dict) -> Optional[User]:
    logger.info(f"Updating preferences for user {user_id}")
    
    try:
        user = await db.get(User, user_id)
        if user:
            user.preferences = preferences
            await db.flush()
            await db.refresh(user)
            logger.info(f"Preferences updated for user {user_id}")
        else:
            logger.warning(f"User {user_id} not found for preferences update")
        return user
    except Exception as e:
        logger.error(f"Failed to update preferences for user {user_id}: {str(e)}", exc_info=True)
        raise

async def update_user_location(db: AsyncSession, user_id: int, latitude: float, longitude: float) -> Optional[User]:
    logger.info(f"Updating location for user {user_id}: ({latitude}, {longitude})")
    
    try:
        user = await db.get(User, user_id)
        if user:
            user.current_latitude = latitude
            user.current_longitude = longitude
            await db.flush()
            await db.refresh(user)
            logger.info(f"Location updated for user {user_id}")
        else:
            logger.warning(f"User {user_id} not found for location update")
        return user
    except Exception as e:
        logger.error(f"Failed to update location for user {user_id}: {str(e)}", exc_info=True)
        raise