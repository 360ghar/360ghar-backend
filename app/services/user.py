from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    BaseAPIException,
    ForbiddenException,
)
from app.core.logging import get_logger
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.user import UserUpdate

logger = get_logger(__name__)

async def get_user_by_phone(db: AsyncSession, phone: str) -> User | None:
    """Fetch a user by phone number, if present.

    Note: Phone numbers are not unique in the schema; this returns the first match
    if multiple exist. For existence checks, this is sufficient.
    """
    logger.debug("Fetching user by phone: %s", phone)
    try:
        stmt = select(User).where(User.phone == phone)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            logger.debug("User found with ID %s for phone %s", user.id, phone)
        else:
            logger.debug("No user found with phone %s", phone)
        return user
    except Exception as e:
        logger.error("Failed to fetch user by phone %s: %s", phone, e, exc_info=True)
        raise

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    logger.debug("Fetching user by email: %s", email)
    try:
        stmt = select(User).where(User.email == email)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            logger.debug("User found with ID %s", user.id)
        else:
            logger.debug("No user found with email %s", email)
        return user
    except Exception as e:
        logger.error("Failed to fetch user by email %s: %s", email, e, exc_info=True)
        raise

async def get_user_by_supabase_id(db: AsyncSession, supabase_user_id: str) -> User | None:
    logger.debug("Fetching user by Supabase ID: %s", supabase_user_id)
    try:
        stmt = select(User).where(User.supabase_user_id == supabase_user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            logger.debug("User found with ID %s", user.id)
        else:
            logger.debug("No user found with Supabase ID %s", supabase_user_id)
        return user
    except Exception as e:
        logger.error("Failed to fetch user by Supabase ID %s: %s", supabase_user_id, e, exc_info=True)
        raise

async def get_or_create_user_from_supabase(db: AsyncSession, supabase_user_data: dict[str, Any]) -> User:
    """Get or create user from Supabase auth data"""
    logger.info("Getting or creating user from Supabase data for user %s", supabase_user_data['id'])

    try:
        # Normalize incoming fields
        supabase_id = supabase_user_data.get("id")
        email = supabase_user_data.get("email") or None
        phone = supabase_user_data.get("phone") or None
        full_name = (supabase_user_data.get("user_metadata") or {}).get("full_name")
        is_verified = bool(supabase_user_data.get("email_verified", False))

        user = await get_user_by_supabase_id(db, supabase_id or "")

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
                logger.info("Updating existing user %s with Supabase ID", user.id)
                user.supabase_user_id = str(supabase_id)
                # Optionally backfill missing phone/full_name
                if phone and not user.phone:
                    user.phone = phone
                if full_name and not user.full_name:
                    user.full_name = full_name
            else:
                # Create new user
                logger.info("Creating new user from Supabase data: phone=%s email=%s", 'present' if phone else 'none', 'present' if email else 'none')
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
                user = await get_user_by_supabase_id(db, str(supabase_id or ""))
                if not user:
                    # Re-raise if still not found; something else went wrong
                    raise
            else:
                await db.refresh(user)
                logger.info("User %s with ID %s", 'updated' if user.supabase_user_id else 'created', user.id)
        else:
            logger.debug("User already exists with ID %s", user.id)

        return user
    except Exception as e:
        logger.error("Failed to get or create user from Supabase: %s", e, exc_info=True)
        raise

async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    """Fetch a user by internal ID."""
    try:
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error("Failed to fetch user by id %s: %s", user_id, e)
        raise

async def get_all_users(
    db: AsyncSession,
    *,
    page: int = 1,
    limit: int = 20,
    search_query: str | None = None,
    filter_agent_id: int | None = None,
) -> tuple[list[User], int]:
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
        users = list(result.scalars().all())

        count_result = await db.execute(count_stmt)
        total = count_result.scalar_one()
        return users, total
    except Exception as e:
        logger.error("Failed to list users: %s", e)
        raise

async def update_user(db: AsyncSession, user_id: int, user_update: UserUpdate, actor: User | None = None) -> User | None:
    logger.info("Updating user %s", user_id)

    try:
        user = await get_user_by_id(db, user_id)

        if not user:
            logger.warning("User %s not found for update", user_id)
            return None

        update_data = user_update.model_dump(exclude_unset=True)
        logger.debug("Updating user %s with fields: %s", user_id, list(update_data.keys()))

        # RBAC: if an actor is provided and actor is an agent updating other users,
        # restrict to safe fields only
        if actor is not None and actor.role == UserRole.agent.value and actor.id != user_id:
            # Ensure the agent is assigned to this user
            if actor.agent_id is None or user.agent_id != actor.agent_id:
                raise ForbiddenException(detail="Agent not authorized to update this user")
            allowed_fields = {
                'email', 'full_name', 'phone', 'profile_image_url',
                'preferences', 'notification_settings', 'privacy_settings'
            }
            update_data = {k: v for k, v in update_data.items() if k in allowed_fields}
            logger.debug("Agent update filtered fields: %s", list(update_data.keys()))
        # Admins can update any fields; end-users can update their own profile via API

        # Handle email update (no uniqueness validation needed since emails are now non-unique)
        if 'email' in update_data:
            new_email = update_data['email']

            # Skip update if email is the same as current
            if new_email == user.email:
                logger.debug("Email unchanged for user %s, skipping email update", user_id)
                del update_data['email']

        # Apply updates
        for field, value in update_data.items():
            setattr(user, field, value)

        await db.flush()
        await db.refresh(user)
        logger.info("User %s updated successfully", user_id)

        return user
    except BaseAPIException:
        # Re-raise custom API exceptions as-is
        raise
    except IntegrityError as e:
        logger.error("Integrity error updating user %s: %s", user_id, e)
        raise BadRequestException(detail="Data integrity constraint violated") from None
    except Exception as e:
        logger.error("Failed to update user %s: %s", user_id, e, exc_info=True)
        raise BaseAPIException(detail="Internal server error occurred while updating user") from None

async def update_user_preferences(db: AsyncSession, user_id: int, preferences: dict) -> User | None:
    logger.info("Updating preferences for user %s", user_id)

    try:
        user = await db.get(User, user_id)
        if user:
            current_preferences = user.preferences if isinstance(user.preferences, dict) else {}
            incoming_preferences = {k: v for k, v in preferences.items() if v is not None}
            user.preferences = {**current_preferences, **incoming_preferences}
            await db.flush()
            await db.refresh(user)
            logger.info("Preferences updated for user %s", user_id)
        else:
            logger.warning("User %s not found for preferences update", user_id)
        return user
    except Exception as e:
        logger.error("Failed to update preferences for user %s: %s", user_id, e, exc_info=True)
        raise

async def update_user_location(db: AsyncSession, user_id: int, latitude: float, longitude: float) -> User | None:
    logger.info("Updating location for user %s: (%s, %s)", user_id, latitude, longitude)

    try:
        user = await db.get(User, user_id)
        if user:
            user.current_latitude = latitude
            user.current_longitude = longitude
            await db.flush()
            await db.refresh(user)
            logger.info("Location updated for user %s", user_id)
        else:
            logger.warning("User %s not found for location update", user_id)
        return user
    except Exception as e:
        logger.error("Failed to update location for user %s: %s", user_id, e, exc_info=True)
        raise


async def update_user_notification_settings(
    db: AsyncSession,
    user_id: int,
    settings: dict,
) -> User | None:
    logger.info("Updating notification settings for user %s", user_id)
    try:
        user = await db.get(User, user_id)
        if user:
            user.notification_settings = settings
            await db.flush()
            await db.refresh(user)
            logger.info("Notification settings updated for user %s", user_id)
        else:
            logger.warning("User %s not found for notification settings update", user_id)
        return user
    except Exception as e:
        logger.error("Failed to update notification settings for user %s: %s", user_id, e, exc_info=True,)
        raise


async def update_user_privacy_settings(
    db: AsyncSession,
    user_id: int,
    settings: dict,
) -> User | None:
    logger.info("Updating privacy settings for user %s", user_id)
    try:
        user = await db.get(User, user_id)
        if user:
            user.privacy_settings = settings
            await db.flush()
            await db.refresh(user)
            logger.info("Privacy settings updated for user %s", user_id)
        else:
            logger.warning("User %s not found for privacy settings update", user_id)
        return user
    except Exception as e:
        logger.error("Failed to update privacy settings for user %s: %s", user_id, e, exc_info=True,)
        raise
