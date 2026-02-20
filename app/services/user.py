from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, func
from sqlalchemy.exc import IntegrityError
from typing import Optional, Dict, Any, List, Tuple
from fastapi import HTTPException, status
from app.models.users import User
from app.models.enums import UserRole
from app.schemas.user import UserUpdate
from app.core.logging import get_logger

logger = get_logger(__name__)

async def get_user_by_phone(db: AsyncSession, phone: str) -> Optional[User]:
    """Fetch a user by phone number, if present.

    Note: Phone numbers are not unique in the schema; this returns the first match
    if multiple exist. For existence checks, this is sufficient.
    """
    logger.debug(f"Fetching user by phone: {phone}")
    try:
        stmt = select(User).where(User.phone == phone)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            logger.debug(f"User found with ID {user.id} for phone {phone}")
        else:
            logger.debug(f"No user found with phone {phone}")
        return user
    except Exception as e:
        logger.error(f"Failed to fetch user by phone {phone}: {str(e)}", exc_info=True)
        raise

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
        # Normalize incoming fields
        supabase_id = supabase_user_data.get("id")
        email = supabase_user_data.get("email") or None
        phone = supabase_user_data.get("phone") or None
        full_name = (supabase_user_data.get("user_metadata") or {}).get("full_name")
        is_verified = bool(supabase_user_data.get("email_verified", False))

        user = await get_user_by_supabase_id(db, supabase_id)
        
        if not user:
            # Prioritize phone lookup over email since phone is now the primary identifier
            if phone:
                user = await get_user_by_phone(db, phone)
            elif email:
                # Fallback to email lookup for backward compatibility with existing users
                user = await get_user_by_email(db, email)
            else:
                user = None
            
            if user:
                # Update with Supabase ID
                logger.info(f"Updating existing user {user.id} with Supabase ID")
                user.supabase_user_id = supabase_id
                # Optionally backfill missing phone/full_name
                if phone and not user.phone:
                    user.phone = phone
                if full_name and not user.full_name:
                    user.full_name = full_name
            else:
                # Create new user
                logger.info(
                    f"Creating new user from Supabase data: "
                    f"phone={'present' if phone else 'none'} email={'present' if email else 'none'}"
                )
                user = User(
                    supabase_user_id=supabase_id,
                    email=email,
                    full_name=full_name,
                    phone=phone,
                    is_active=True,
                    is_verified=is_verified
                )
                db.add(user)
            # Flush with protection against race-condition duplicates on supabase_user_id
            try:
                await db.flush()
            except IntegrityError as ie:
                logger.warning(
                    "IntegrityError during user insert/update, attempting to recover by fetching existing user: %s",
                    str(ie)
                )
                await db.rollback()
                # Another request likely created the user already; fetch and return it
                user = await get_user_by_supabase_id(db, supabase_id)
                if not user:
                    # Re-raise if still not found; something else went wrong
                    raise
            else:
                await db.refresh(user)
                logger.info(f"User {'updated' if user.supabase_user_id else 'created'} with ID {user.id}")
        else:
            logger.debug(f"User already exists with ID {user.id}")
        
        return user
    except Exception as e:
        logger.error(f"Failed to get or create user from Supabase: {str(e)}", exc_info=True)
        raise

async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    """Fetch a user by internal ID."""
    try:
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Failed to fetch user by id {user_id}: {e}")
        raise

async def get_all_users(
    db: AsyncSession,
    *,
    page: int = 1,
    limit: int = 20,
    search_query: Optional[str] = None,
    filter_agent_id: Optional[int] = None,
) -> Tuple[List[User], int]:
    """Return users with optional agent filter and search, with pagination."""
    try:
        offset = (page - 1) * limit
        conditions = []
        if filter_agent_id is not None:
            conditions.append(User.agent_id == filter_agent_id)
        if search_query:
            q = f"%{search_query}%"
            conditions.append(or_(User.full_name.ilike(q), User.email.ilike(q), User.phone.ilike(q)))

        stmt = select(User)
        count_stmt = select(func.count()).select_from(User)
        if conditions:
            stmt = stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))
        stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)
        result = await db.execute(stmt)
        users = result.scalars().all()

        count_result = await db.execute(count_stmt)
        total = count_result.scalar_one()
        return users, total
    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        raise

async def update_user(db: AsyncSession, user_id: int, user_update: UserUpdate, actor: Optional[User] = None) -> Optional[User]:
    logger.info(f"Updating user {user_id}")
    
    try:
        user = await get_user_by_id(db, user_id)
        
        if not user:
            logger.warning(f"User {user_id} not found for update")
            return None
        
        update_data = user_update.model_dump(exclude_unset=True)
        logger.debug(f"Updating user {user_id} with fields: {list(update_data.keys())}")

        # RBAC: if an actor is provided and actor is an agent updating other users,
        # restrict to safe fields only
        if actor is not None and actor.role == UserRole.agent.value and actor.id != user_id:
            # Ensure the agent is assigned to this user
            if actor.agent_id is None or user.agent_id != actor.agent_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Agent not authorized to update this user",
                )
            allowed_fields = {
                'email', 'full_name', 'phone', 'profile_image_url',
                'preferences', 'notification_settings', 'privacy_settings'
            }
            update_data = {k: v for k, v in update_data.items() if k in allowed_fields}
            logger.debug(f"Agent update filtered fields: {list(update_data.keys())}")
        # Admins can update any fields; end-users can update their own profile via API
        
        # Handle email update (no uniqueness validation needed since emails are now non-unique)
        if 'email' in update_data:
            new_email = update_data['email']
            
            # Skip update if email is the same as current
            if new_email == user.email:
                logger.debug(f"Email unchanged for user {user_id}, skipping email update")
                del update_data['email']
        
        # Apply updates
        for field, value in update_data.items():
            setattr(user, field, value)
        
        await db.flush()
        await db.refresh(user)
        logger.info(f"User {user_id} updated successfully")
        
        return user
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except IntegrityError as e:
        logger.error(f"Integrity error updating user {user_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Data integrity constraint violated"
        )
    except Exception as e:
        logger.error(f"Failed to update user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred while updating user"
        )

async def update_user_preferences(db: AsyncSession, user_id: int, preferences: dict) -> Optional[User]:
    logger.info(f"Updating preferences for user {user_id}")
    
    try:
        user = await db.get(User, user_id)
        if user:
            current_preferences = user.preferences if isinstance(user.preferences, dict) else {}
            incoming_preferences = {k: v for k, v in preferences.items() if v is not None}
            user.preferences = {**current_preferences, **incoming_preferences}
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


async def update_user_notification_settings(
    db: AsyncSession,
    user_id: int,
    settings: dict,
) -> Optional[User]:
    logger.info(f"Updating notification settings for user {user_id}")
    try:
        user = await db.get(User, user_id)
        if user:
            user.notification_settings = settings
            await db.flush()
            await db.refresh(user)
            logger.info(f"Notification settings updated for user {user_id}")
        else:
            logger.warning(f"User {user_id} not found for notification settings update")
        return user
    except Exception as e:
        logger.error(
            f"Failed to update notification settings for user {user_id}: {str(e)}",
            exc_info=True,
        )
        raise


async def update_user_privacy_settings(
    db: AsyncSession,
    user_id: int,
    settings: dict,
) -> Optional[User]:
    logger.info(f"Updating privacy settings for user {user_id}")
    try:
        user = await db.get(User, user_id)
        if user:
            user.privacy_settings = settings
            await db.flush()
            await db.refresh(user)
            logger.info(f"Privacy settings updated for user {user_id}")
        else:
            logger.warning(f"User {user_id} not found for privacy settings update")
        return user
    except Exception as e:
        logger.error(
            f"Failed to update privacy settings for user {user_id}: {str(e)}",
            exc_info=True,
        )
        raise
