from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    BaseAPIException,
    ForbiddenException,
    ServiceUnavailableException,
    ValidationException,
)
from app.core.logging import get_logger
from app.core.utils import utc_now
from app.models.enums import AuthMethod, UserRole
from app.models.users import User
from app.schemas.user import UserUpdate
from app.utils.validators import ValidationUtils

logger = get_logger(__name__)


def _normalize_phone(phone: str | None) -> str | None:
    """Strip international prefixes and keep only digits for comparison.

    Handles formats like '+918178340031', '00918178340031', '918178340031'.
    Returns the last 10 digits (Indian mobile) or the full digit string.
    """
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) > 10:
        digits = digits[-10:]
    return digits if digits else None

async def get_user_by_phone(db: AsyncSession, phone: str) -> User | None:
    """Fetch a user by phone number, if present.

    Phone has a unique constraint, so this returns at most one user.
    Tries exact match first, then normalized (last-10-digits) match.
    Prioritizes active users over inactive ones if duplicates exist.
    """
    logger.debug("Fetching user by phone: %s", phone)
    try:
        stmt = select(User).where(User.phone == phone).order_by(User.is_active.desc(), User.created_at.desc())
        result = await db.execute(stmt)
        user = result.scalars().first()
        if user:
            logger.debug("User found with ID %s for phone %s", user.id, phone)
            return user
        # Fallback: match on normalized phone (last 10 digits)
        norm = _normalize_phone(phone)
        if norm:
            stmt_norm = select(User).where(
                func.replace(func.replace(func.replace(User.phone, "+", ""), "-", ""), " ", "").like(f"%{norm}")
            ).order_by(User.is_active.desc(), User.created_at.desc())
            result_norm = await db.execute(stmt_norm)
            user = result_norm.scalars().first()
            if user:
                logger.debug("User found via normalized phone match: ID %s for phone %s", user.id, phone)
                return user
        logger.debug("No user found with phone %s", phone)
        return None
    except Exception as e:
        logger.error("Failed to fetch user by phone %s: %s", phone, e, exc_info=True)
        raise

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    logger.debug("Fetching user by email: %s", email)
    try:
        stmt = select(User).where(User.email == email).order_by(User.is_active.desc(), User.created_at.desc())
        result = await db.execute(stmt)
        user = result.scalars().first()
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
        user = result.scalars().first()
        if user:
            logger.debug("User found with ID %s", user.id)
        else:
            logger.debug("No user found with Supabase ID %s", supabase_user_id)
        return user
    except Exception as e:
        logger.error("Failed to fetch user by Supabase ID %s: %s", supabase_user_id, e, exc_info=True)
        raise

async def get_or_create_user_from_supabase(db: AsyncSession, supabase_user_data: dict[str, Any]) -> User:
    """Get or create a local user mirroring a Supabase auth user.

    Email is the canonical linking key (email-linked, multi-method identity).
    Precedence:
      1. Find by ``supabase_user_id`` → return as-is.
      2. Fallback dedup by VERIFIED email only (only when the incoming token's
         ``email_confirmed_at`` is set), then by ``phone``.
      3. No match → create a new user.

    Legacy duplicate handling: if a local row is found by email/phone whose
    ``supabase_user_id`` differs from the incoming canonical id, REPOINT that
    row's ``supabase_user_id`` to the incoming id (logged) rather than creating
    a second row. This preserves ownership of properties/visits.
    """
    logger.debug("Getting or creating user from Supabase data for user %s", supabase_user_data['id'])

    try:
        # Normalize incoming fields
        supabase_id = str(supabase_user_data.get("id") or "")
        email = supabase_user_data.get("email") or None
        phone = supabase_user_data.get("phone") or None
        full_name = (supabase_user_data.get("user_metadata") or {}).get("full_name")
        email_verified = bool(supabase_user_data.get("email_verified", False))
        phone_verified = bool(supabase_user_data.get("phone_verified", False))
        # Per-channel confirmation drives the email-linking decision: we ONLY
        # dedup by / persist an email when that email is actually confirmed,
        # driven SOLELY by email_confirmed_at. The aggregate `email_verified`
        # flag is true when EITHER channel is confirmed, so a phone-verified
        # user with an unconfirmed email would otherwise have that unconfirmed
        # email persisted into the unique email column — which we must avoid.
        email_confirmed = supabase_user_data.get("email_confirmed_at") is not None

        inactive_user = None

        # (1) Canonical lookup by supabase_user_id.
        user = await get_user_by_supabase_id(db, supabase_id)

        if user and user.is_active:
            logger.debug("User already exists with ID %s", user.id)
            return user

        if user and not user.is_active:
            # Found an inactive duplicate — skip it so we can find the active
            # account via phone/email dedup below.
            inactive_user = user
            logger.info(
                "Supabase ID %s maps to inactive user %s — falling back to phone/email dedup",
                supabase_id,
                user.id,
            )
            user = None

            # Before generic lookup, try to find an ACTIVE user with the same
            # normalized phone.  This handles the common case where a duplicate
            # (inactive) row was created with a slightly different phone format.
            if phone:
                norm = _normalize_phone(phone)
                if norm:
                    active_by_phone = await db.execute(
                        select(User).where(
                            User.is_active.is_(True),
                            func.replace(
                                func.replace(func.replace(User.phone, "+", ""), "-", ""),
                                " ", "",
                            ).like(f"%{norm}"),
                        )
                    )
                    active_match = active_by_phone.scalars().first()
                    if active_match:
                        logger.info(
                            "Found active user %s via normalized phone match for inactive user %s",
                            active_match.id,
                            inactive_user.id,
                        )
                        # Transfer the supabase_user_id from the inactive row
                        # to the active one so future logins resolve directly.
                        if active_match.supabase_user_id != supabase_id:
                            # Release the old claim first to avoid unique violation
                            inactive_user.supabase_user_id = f"__migrated__{inactive_user.id}"
                            active_match.supabase_user_id = supabase_id
                        await db.flush()
                        await db.refresh(active_match)
                        return active_match

        # (2) Fallback dedup: VERIFIED email first, then phone.
        if email and email_confirmed:
            user = await get_user_by_email(db, email)
        if not user and phone:
            user = await get_user_by_phone(db, phone)

        if user:
            # Account linking / legacy-duplicate repoint: repoint the existing
            # row to the incoming canonical supabase_user_id.
            if user.supabase_user_id != supabase_id:
                logger.info(
                    "Repointing local user %s: supabase_user_id %s -> %s "
                    "(matched by %s; email=%s phone=%s)",
                    user.id,
                    user.supabase_user_id,
                    supabase_id,
                    "email" if (email and email_confirmed and user.email == email) else "phone",
                    "present" if email else "none",
                    "present" if phone else "none",
                )
                if inactive_user and inactive_user.supabase_user_id == supabase_id:
                    inactive_user.supabase_user_id = f"__migrated__{inactive_user.id}"
                user.supabase_user_id = supabase_id
            # Backfill missing fields without overwriting existing data.
            # Skip the phone backfill if that phone already belongs to a
            # DIFFERENT local user (phone is unique-when-present) — adopting it
            # would violate the unique constraint.
            if phone and not user.phone:
                phone_owner = await get_user_by_phone(db, phone)
                if phone_owner is None or phone_owner.id == user.id:
                    user.phone = phone
                else:
                    logger.info(
                        "Skipping phone backfill for user %s: phone already owned by user %s",
                        user.id,
                        phone_owner.id,
                    )
            if full_name and not user.full_name:
                user.full_name = full_name
            # Only adopt the incoming email when the row has none AND the email
            # is verified (never overwrite, never attach an unverified email
            # that could collide with the unique constraint).
            if email and email_confirmed and not user.email:
                email_owner = await get_user_by_email(db, email)
                if email_owner is None or email_owner.id == user.id:
                    user.email = email
                else:
                    logger.info(
                        "Skipping email backfill for user %s: email already owned by user %s",
                        user.id,
                        email_owner.id,
                    )
            # Mirror verification state from the token.
            if email_verified:
                user.email_verified = True
            if phone_verified:
                user.phone_verified = True
        else:
            # (3) Create a new local user.
            logger.info(
                "Creating new user from Supabase data: phone=%s email=%s email_confirmed=%s",
                "present" if phone else "none",
                "present" if email else "none",
                email_confirmed,
            )
            if inactive_user and inactive_user.supabase_user_id == supabase_id:
                inactive_user.supabase_user_id = f"__migrated__{inactive_user.id}"
            user = User(
                supabase_user_id=supabase_id,
                # Only persist an email locally when it is verified, so the
                # unique-email linking key never holds unconfirmed addresses.
                email=email if (email and email_confirmed) else None,
                full_name=full_name,
                phone=phone,
                is_active=True,
                is_verified=email_verified,
                email_verified=email_verified,
                phone_verified=phone_verified,
            )
            db.add(user)

        # Flush with protection against race-condition / legacy duplicates.
        try:
            await db.flush()
        except IntegrityError as ie:
            logger.warning(
                "IntegrityError during user insert/update, reconciling by "
                "supabase_user_id -> email -> phone: %s",
                str(ie),
            )
            await db.rollback()
            reconciled = await get_user_by_supabase_id(db, supabase_id)
            if not reconciled and email and email_confirmed:
                reconciled = await get_user_by_email(db, email)
            if not reconciled and phone:
                reconciled = await get_user_by_phone(db, phone)
            if not reconciled:
                raise
            if reconciled.supabase_user_id != supabase_id:
                reconciled.supabase_user_id = supabase_id
                await db.flush()
            user = reconciled
        else:
            await db.refresh(user)
            logger.info("User synced from Supabase with ID %s", user.id)

        return user
    except Exception as e:
        logger.error("Failed to get or create user from Supabase: %s", e, exc_info=True)
        raise


async def set_last_auth_method(db: AsyncSession, user: User, method: AuthMethod) -> User:
    """Record the last authentication method used by ``user``.

    Stores both the method (TEXT, CHECK-constrained in the DB) and the UTC
    timestamp. Returns the refreshed user.
    """
    logger.debug("Setting last_auth_method=%s for user %s", method, user.id)
    user.last_auth_method = method.value
    user.last_auth_method_at = utc_now()
    await db.flush()
    await db.refresh(user)
    return user


def _normalize_phone_to_e164(identifier: str) -> str:
    """Normalize a phone identifier to E.164 for matching ``auth.users.phone``.

    Reuses :meth:`ValidationUtils.validate_phone` (India default +91). On a
    malformed input it returns the stripped raw value unchanged so the
    ``WHERE phone = :phone`` clause simply yields no match (``exists=False``),
    mirroring the prior not-found semantics — it NEVER raises.
    """
    raw = identifier.strip()
    try:
        normalized = ValidationUtils.validate_phone(raw)
    except ValidationException:
        return raw
    return normalized or raw


async def get_identifier_status(db: AsyncSession, identifier: str) -> dict[str, Any]:
    """Compute the auth status of an identifier for the login state-machine.

    Detects the channel (``'@' in identifier`` → email, else phone) and looks
    the identifier up directly in Supabase's ``auth.users`` table. This is the
    authoritative source: ``encrypted_password IS NOT NULL`` reliably reports
    whether a password credential exists (the prior GoTrue
    ``app_metadata.providers`` heuristic did not), and ``*_confirmed_at``
    reports channel verification.

    Returns a dict with keys:
      - ``exists``: the identifier maps to an auth user
      - ``verified``: the matching channel is confirmed (email/phone)
      - ``has_password``: a password credential exists for the user
      - ``channel``: ``"email"`` or ``"phone"``
      - ``next_step``: ``"password"`` iff exists AND verified AND has_password,
        else ``"otp"``

    Raises:
      ServiceUnavailableException: If the ``auth.users`` lookup fails (DB
        connectivity / permissions). This prevents treating existing users as
        new during transient outages.
    """
    channel = "email" if "@" in identifier else "phone"

    try:
        if channel == "email":
            # GoTrue stores emails lowercased; `lower()` is applied to the bound
            # value (not the column) so the unique btree index on `email` is
            # still usable.
            stmt = text(
                """
                SELECT id, email, phone,
                       email_confirmed_at, phone_confirmed_at,
                       (encrypted_password IS NOT NULL) AS has_password
                FROM auth.users
                WHERE email = lower(:email)
                LIMIT 1
                """
            )
            params: dict[str, Any] = {"email": identifier.strip()}
        else:
            # GoTrue stores auth.users.phone WITHOUT a leading "+" (e.g.
            # "916280137577"); the normalized E.164 form has it ("+916280137577").
            # Match both forms so the lookup is robust to either storage style.
            # removeprefix strips at most one "+" so malformed input can't be
            # massaged into a valid key (lstrip would strip every "+").
            phone_value = _normalize_phone_to_e164(identifier)
            phone_noplus = phone_value.removeprefix("+")
            stmt = text(
                """
                SELECT id, email, phone,
                       email_confirmed_at, phone_confirmed_at,
                       (encrypted_password IS NOT NULL) AS has_password
                FROM auth.users
                WHERE phone IN (:phone_e164, :phone_noplus)
                LIMIT 1
                """
            )
            params = {"phone_e164": phone_value, "phone_noplus": phone_noplus}

        result = await db.execute(stmt, params)
        row = result.mappings().first()
    except Exception as exc:  # noqa: BLE001 — any failure must not misroute
        # Log only the exception type, never the message: SQLAlchemy DBAPI
        # errors can include the SQL and bound params (the user's email/phone),
        # which must not reach production logs on this public endpoint.
        logger.warning(
            "identifier-status: auth.users lookup failed for %s channel (err=%s)",
            channel,
            type(exc).__name__,
        )
        raise ServiceUnavailableException(
            detail="Identity provider is temporarily unavailable, please retry",
        ) from exc

    exists = row is not None
    verified = False
    has_password = False

    if row:
        if channel == "email":
            verified = row["email_confirmed_at"] is not None
        else:
            verified = row["phone_confirmed_at"] is not None
        has_password = bool(row["has_password"])

    next_step = "password" if (exists and verified and has_password) else "otp"

    return {
        "exists": exists,
        "verified": verified,
        "has_password": has_password,
        "channel": channel,
        "next_step": next_step,
    }

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
            if field == "profile_image_url" and value is not None and not ValidationUtils.is_absolute_url(value):
                logger.warning("Non-absolute profile_image_url for user %s: %s", user_id, value)
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
