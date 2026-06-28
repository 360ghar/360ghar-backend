from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import _is_failure, admin_delete_user
from app.core.exceptions import (
    BadRequestException,
    BaseAPIException,
    ForbiddenException,
    ServiceUnavailableException,
    ValidationException,
)
from app.core.logging import get_logger
from app.core.utils import utc_now
from app.models.enums import AuthMethod, FlatmatesProfileStatus, UserRole
from app.models.users import User
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value
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
        stmt = (
            select(User)
            .where(User.phone == phone)
            .order_by(User.is_active.desc(), User.created_at.desc())
        )
        result = await db.execute(stmt)
        user = result.scalars().first()
        if user:
            logger.debug("User found with ID %s for phone %s", user.id, phone)
            return user
        # Fallback: match on normalized phone (last 10 digits)
        norm = _normalize_phone(phone)
        if norm:
            stmt_norm = (
                select(User)
                .where(
                    func.replace(
                        func.replace(func.replace(User.phone, "+", ""), "-", ""), " ", ""
                    ).like(f"%{norm}")
                )
                .order_by(User.is_active.desc(), User.created_at.desc())
            )
            result_norm = await db.execute(stmt_norm)
            user = result_norm.scalars().first()
            if user:
                logger.debug(
                    "User found via normalized phone match: ID %s for phone %s", user.id, phone
                )
                return user
        logger.debug("No user found with phone %s", phone)
        return None
    except Exception as e:
        logger.error("Failed to fetch user by phone %s: %s", phone, e, exc_info=True)
        raise


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    logger.debug("Fetching user by email: %s", email)
    try:
        stmt = (
            select(User)
            .where(User.email == email)
            .order_by(User.is_active.desc(), User.created_at.desc())
        )
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
        logger.error(
            "Failed to fetch user by Supabase ID %s: %s", supabase_user_id, e, exc_info=True
        )
        raise


async def get_or_create_user_from_supabase(
    db: AsyncSession, supabase_user_data: dict[str, Any]
) -> User:
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
    logger.debug(
        "Getting or creating user from Supabase data for user %s", supabase_user_data["id"]
    )

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

        # Serialize concurrent first-time creates for the SAME Supabase user.
        # Right after login the frontend fires several authenticated requests in
        # parallel (profile + auth-state); without this lock two of them can
        # both reach the create branch (3) below and INSERT the same new row.
        # The loser's flush raises IntegrityError, and the reconciliation below
        # then can't see the winner's still-uncommitted row (READ COMMITTED;
        # get_db commits only at request end) → it re-raises → the auth
        # dependency returns a spurious 401 AUTHENTICATION_FAILED → the frontend
        # loop. A transaction-scoped advisory lock keyed on supabase_user_id
        # makes the loser block until the winner commits, so its lookup sees the
        # committed row instead of racing. xact-scoped (not session-scoped) so
        # it is safe under PgBouncer transaction pooling and released at commit.
        if supabase_id:
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:sid))"),
                {"sid": supabase_id},
            )

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
                                " ",
                                "",
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
            # is_verified = True when EITHER channel is confirmed.
            if email_verified or phone_verified:
                user.is_verified = True
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
                # is_verified = True when EITHER channel is confirmed.
                is_verified=email_verified or phone_verified,
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
    user.last_auth_method = method
    user.last_auth_method_at = utc_now()
    await db.flush()
    await db.refresh(user)
    return user


async def delete_user_account(db: AsyncSession, user: User) -> None:
    """Permanently delete ``user``'s account (App Store Guideline 5.1.1(v)).

    The account becomes **permanently unusable**:

    1. The Supabase Auth user is **hard-deleted** via the GoTrue Admin API,
       which immediately invalidates all of the user's sessions and refresh
       tokens (session revocation) and removes the identity from Supabase
       Auth. ``device_tokens`` / ``notifications`` referencing ``auth.users``
       are nullified by their ``ON DELETE SET NULL`` rules.
    2. The local ``users`` row is **anonymized and soft-deleted** —
       ``is_active = False``, all PII nulled, ``supabase_user_id`` tombstoned.
       Soft-delete preserves referential integrity with properties/visits/
       bookings; the PII scrub satisfies the data-removal requirement.

    Raises :class:`ServiceUnavailableException` (503) if the identity provider
    is unreachable, or :class:`BaseAPIException` (500) if deletion fails for
    another reason — the local row is left untouched in either case so the
    caller can retry. ``admin_delete_user`` is idempotent (404 → success), so
    retries after a partial failure are safe.
    """
    supabase_user_id = user.supabase_user_id

    result = await admin_delete_user(supabase_user_id)
    if _is_failure(result):
        # Transient network/DNS error → advise the client to retry; do NOT
        # touch the local row so the account stays intact until success.
        logger.warning(
            "Account deletion aborted for user %s: identity provider unreachable",
            user.id,
        )
        raise ServiceUnavailableException(
            detail="Identity provider is temporarily unavailable, please retry",
            headers={"Retry-After": "30"},
        )
    if result is not True:
        # GoTrue returned a non-success, non-404 status — unexpected infra
        # error. Surface a retryable error; the local row is unchanged.
        logger.error(
            "Account deletion failed for user %s: Supabase auth delete unsuccessful",
            user.id,
        )
        raise BaseAPIException(detail="Failed to delete account, please try again")

    # Anonymize PII + soft-delete locally. The ``__deleted__`` tombstone on
    # ``supabase_user_id`` releases the unique claim and marks the row clearly
    # (mirrors the existing ``__migrated__`` convention in user reconciliation).
    user.is_active = False
    user.supabase_user_id = f"__deleted__{user.id}"

    # Delete avatar from storage before nullifying the URL so we don't leave
    # orphaned files.  Best-effort: a failure here should not abort the
    # account deletion (the Supabase auth user is already hard-deleted).
    if user.profile_image_url:
        try:
            from app.services.storage import storage_service

            old_path = storage_service.extract_path_from_url(user.profile_image_url)
            if old_path:
                storage_service.delete_file(old_path)
        except Exception:
            logger.warning(
                "Failed to delete avatar from storage for user %s during account deletion",
                user.id,
            )

    # Identity & contact PII
    user.email = None
    user.phone = None
    user.full_name = None
    user.profile_image_url = None
    user.date_of_birth = None
    user.email_verified = False
    user.phone_verified = False
    # Location PII
    user.current_latitude = None
    user.current_longitude = None
    # Preference payloads (may carry personal data)
    user.preferences = None
    user.notification_settings = None
    user.privacy_settings = None
    # Flatmates profile PII (shared backend also serves the flatmates app)
    user.flatmates_mode = None
    user.flatmates_bio = None
    user.flatmates_city = None
    user.flatmates_locality = None
    user.flatmates_budget_min = None
    user.flatmates_budget_max = None
    user.flatmates_move_in_timeline = None
    user.flatmates_sleep_schedule = None
    user.flatmates_cleanliness = None
    user.flatmates_food_habits = None
    user.flatmates_smoking_drinking = None
    user.flatmates_guests_policy = None
    user.flatmates_work_style = None
    # Verification & status fields
    user.is_verified = False
    user.flatmates_profile_status = FlatmatesProfileStatus.draft
    user.flatmates_onboarding_completed = False
    user.flatmates_last_active_at = None
    # Auth metadata & cross-app onboarding
    user.last_auth_method = None
    user.last_auth_method_at = None
    user.stays_onboarding_completed = False
    user.estate_onboarding_completed = False
    user.ghar360_onboarding_completed = False
    await db.flush()
    logger.info(
        "User %s account deleted (Supabase auth user removed, local PII anonymized)",
        user.id,
    )


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


# ── Auth gate-state computation ──────────────────────────────────────────────
# The gate model: IDENTIFIER_VERIFICATION -> PASSWORD_SETUP -> PROFILE_COMPLETION
# -> APP_ONBOARDING -> ACTIVE.  Computed here (single source of truth) so the
# clients just read the stage from GET /users/me/auth-state and route accordingly.
#
# No denormalized gate columns are used.  Every gate is evaluated from the
# actual field values on each request, so there is zero drift risk.


# Mandatory profile fields for the PROFILE_COMPLETION gate.
# Default applies to all apps unless overridden in _APP_PROFILE_FIELDS.
_PROFILE_REQUIRED_FIELDS: tuple[str, ...] = ("full_name", "date_of_birth")

# Per-app profile field overrides.  Apps not listed use the default above.
_APP_PROFILE_FIELDS: dict[str, tuple[str, ...]] = {
    # "estate": ("full_name", "date_of_birth", "company_name"),  # example
}


# ── Multi-app onboarding registry ────────────────────────────────────────────
# Each app registers a callable that inspects the live User row and returns
# True when that app's onboarding is complete.  New apps call
# ``register_app_onboarding_check("stays", fn)`` during startup.
#
# All four consumer apps are registered here.  The check is a simple boolean
# column on the users table; more complex apps can override via
# ``register_app_onboarding_check`` at startup.

_APP_ONBOARDING_CHECKS: dict[str, Callable[[User], bool]] = {
    "flatmates": lambda u: bool(getattr(u, "flatmates_onboarding_completed", False)),
    "stays": lambda u: bool(getattr(u, "stays_onboarding_completed", False)),
    "estate": lambda u: bool(getattr(u, "estate_onboarding_completed", False)),
    # NOTE: ghar360 has no auth-level onboarding flow (its first-launch intro
    # is handled locally via GetStorage hasSeenOnboarding). It is intentionally
    # absent so the gate never returns app_onboarding for it; the column
    # ``ghar360_onboarding_completed`` exists for future use.
}

# Maps an app slug to the User column that records its onboarding completion.
# Used by :func:`complete_app_onboarding` to persist completion. Must stay in
# sync with ``_APP_ONBOARDING_CHECKS``: only apps with an actual onboarding
# flow belong here. ``ghar360`` is intentionally absent (no auth-level
# onboarding — see the NOTE above), so completing it raises
# ``BadRequestException``. The ``ghar360_onboarding_completed`` column is kept
# for future use.
_APP_ONBOARDING_COLUMNS: dict[str, str] = {
    "flatmates": "flatmates_onboarding_completed",
    "stays": "stays_onboarding_completed",
    "estate": "estate_onboarding_completed",
}


def register_app_onboarding_check(app: str, check: Callable[[User], bool]) -> None:
    """Register an onboarding-completion check for a new app.

    ``check`` receives the live :class:`User` row and must return ``True``
    when that app's onboarding is complete.
    """
    _APP_ONBOARDING_CHECKS[app] = check


async def complete_app_onboarding(db: AsyncSession, user: User, *, app: str) -> User:
    """Mark the given app's onboarding as complete for ``user``.

    Sets the matching ``<app>_onboarding_completed`` column to ``True`` and
    returns the refreshed user.  Raises :class:`BadRequestException` if the
    app slug is unknown (no onboarding flow to complete).
    """
    column = _APP_ONBOARDING_COLUMNS.get(app)
    if column is None:
        raise BadRequestException(detail=f"Unknown app slug: {app}")
    logger.info("Marking onboarding complete for user %s app=%s", user.id, app)
    setattr(user, column, True)
    await db.flush()
    await db.refresh(user)
    return user


async def compute_auth_gate_state(
    db: AsyncSession, user: User, *, app: str = "flatmates"
) -> dict[str, Any]:
    """Compute the current auth gate stage for a user.

    Parameters:
        db: the async DB session.
        user: the live :class:`User` row (field values read as-is).
        app: the app slug whose onboarding to check (``"flatmates"``,
            ``"stays"``, etc.).  Defaults to ``"flatmates"``.

    Returns a dict:
      - ``stage``: the current gate (``identifier_verification``,
        ``password_setup``, ``profile_completion``, ``app_onboarding``,
        ``active``)
      - ``next_action``: what the client should do next
      - ``missing_fields``: list of profile fields still required (if applicable)
    """
    # ── IDENTIFIER_VERIFICATION: is at least one channel confirmed? ──────
    if not user.email_verified and not user.phone_verified:
        return {
            "stage": "identifier_verification",
            "next_action": "verify_identifier",
            "missing_fields": [],
        }

    # ── PASSWORD_SETUP: does the account have a password? ────────────────
    # Queried from auth.users because the local mirror does not store it.
    has_password = await _check_user_has_password(db, user.supabase_user_id)
    if not has_password:
        return {
            "stage": "password_setup",
            "next_action": "set_password",
            "missing_fields": [],
        }

    # ── PROFILE_COMPLETION: are all mandatory fields present? ────────────
    profile_fields = _APP_PROFILE_FIELDS.get(app, _PROFILE_REQUIRED_FIELDS)
    missing = [field for field in profile_fields if not getattr(user, field, None)]
    if missing:
        return {
            "stage": "profile_completion",
            "next_action": "complete_profile",
            "missing_fields": missing,
        }

    # ── APP_ONBOARDING: look up the app-specific check from the registry. ─
    onboarding_check = _APP_ONBOARDING_CHECKS.get(app, lambda u: True)
    try:
        onboarding_complete = onboarding_check(user)
    except Exception as exc:  # noqa: BLE001  fail closed for the auth gate
        logger.warning(
            "Onboarding check failed for app=%s user=%s (err=%s), defaulting to incomplete",
            app,
            user.id,
            type(exc).__name__,
        )
        onboarding_complete = False
    if not onboarding_complete:
        return {
            "stage": "app_onboarding",
            "next_action": "complete_onboarding",
            "missing_fields": [],
        }

    # ── ACTIVE ───────────────────────────────────────────────────────────
    return {
        "stage": "active",
        "next_action": "grant_access",
        "missing_fields": [],
    }


async def _check_user_has_password(db: AsyncSession, supabase_user_id: str) -> bool:
    """Check whether the Supabase auth user has a password credential."""
    try:
        stmt = text(
            "SELECT (encrypted_password IS NOT NULL) AS has_password "
            "FROM auth.users WHERE id = :uid LIMIT 1"
        )
        result = await db.execute(stmt, {"uid": supabase_user_id})
        row = result.mappings().first()
        return bool(row and row["has_password"]) if row else False
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "auth-state: password check failed for %s (err=%s)",
            supabase_user_id,
            type(exc).__name__,
        )
        # On failure, assume password exists so we don't block the user
        # unnecessarily (the gate can be re-evaluated on next request).
        return True


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
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
    search_query: str | None = None,
    filter_agent_id: int | None = None,
) -> tuple[list[User], dict | None, int | None]:
    """Return users with optional agent filter and search, keyset-paginated."""
    try:
        conditions = []
        if filter_agent_id is not None:
            conditions.append(User.agent_id == filter_agent_id)
        if search_query:
            q = f"%{search_query}%"
            conditions.append(
                or_(User.full_name.ilike(q), User.email.ilike(q), User.phone.ilike(q))
            )

        stmt = select(User)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        count_total = None
        if with_total:
            count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
            count_total = count_result.scalar_one()

        predicate = keyset_filter(User.created_at, User.id, cursor_payload, descending=True)
        if predicate is not None:
            stmt = stmt.where(predicate)
        stmt = stmt.order_by(User.created_at.desc(), User.id.desc()).limit(limit + 1)
        result = await db.execute(stmt)
        users = list(result.scalars().all())

        next_payload = None
        if len(users) > limit:
            users = users[:limit]
            next_payload = keyset_payload(keyset_sort_value(users[-1].created_at), users[-1].id)

        return users, next_payload, count_total
    except Exception as e:
        logger.error("Failed to list users: %s", e)
        raise


async def update_user(
    db: AsyncSession, user_id: int, user_update: UserUpdate, actor: User | None = None
) -> User | None:
    logger.info("Updating user %s", user_id)

    try:
        user = await get_user_by_id(db, user_id)

        if not user:
            logger.warning("User %s not found for update", user_id)
            return None

        update_data = user_update.model_dump(exclude_unset=True)
        logger.debug("Updating user %s with fields: %s", user_id, list(update_data.keys()))

        # RBAC: enforce role-based authorization on the target user.
        #  - admins can update any user
        #  - agents can update a limited field set for users assigned to them
        #  - all other roles (regular users) can only update their own profile
        if actor is not None and actor.role != UserRole.admin.value:
            if actor.role == UserRole.agent.value and actor.id != user_id:
                # Ensure the agent is assigned to this user
                if actor.agent_id is None or user.agent_id != actor.agent_id:
                    raise ForbiddenException(detail="Agent not authorized to update this user")
                # Agents can update display and preference fields but NOT
                # identity/contact fields (email, phone) — changing those
                # would let an agent take over a user's account.
                allowed_fields = {
                    "full_name",
                    "profile_image_url",
                    "preferences",
                    "notification_settings",
                    "privacy_settings",
                }
                update_data = {k: v for k, v in update_data.items() if k in allowed_fields}
                logger.debug("Agent update filtered fields: %s", list(update_data.keys()))
            elif actor.id != user_id:
                # Regular users (and any non-admin, non-agent role) can only
                # update their own profile. Without this check, any authenticated
                # user could mutate another user's record by knowing the user_id.
                raise ForbiddenException(detail="Not authorized to update this user")
        # Admins can update any fields; end-users can update their own profile via API

        # Handle email update (no uniqueness validation needed since emails are now non-unique)
        if "email" in update_data:
            new_email = update_data["email"]

            # Skip update if email is the same as current
            if new_email == user.email:
                logger.debug("Email unchanged for user %s, skipping email update", user_id)
                del update_data["email"]
            else:
                # Email changed — reset email_verified so the new address
                # must be confirmed before it is trusted.  Without this,
                # a user could swap to an unverified address and retain
                # the verified flag from the old one.
                user.email_verified = False
                logger.debug("Email changed for user %s, resetting email_verified", user_id)

        # Handle phone update symmetrically: a changed phone must be
        # re-confirmed via OTP, so reset phone_verified.  Without this a user
        # could change their phone via PUT /users/me and keep phone_verified=True.
        if "phone" in update_data and update_data["phone"] != user.phone:
            user.phone_verified = False
            logger.debug("Phone changed for user %s, resetting phone_verified", user_id)

        # Recompute the aggregate is_verified flag after any per-channel reset
        # above so it stays consistent with email_verified / phone_verified.
        user.is_verified = bool(user.email_verified or user.phone_verified)

        # Apply updates
        for field, value in update_data.items():
            if (
                field == "profile_image_url"
                and value is not None
                and not ValidationUtils.is_absolute_url(value)
            ):
                # Reject non-http(s) URLs instead of silently storing them —
                # a ``javascript:`` / ``data:`` value would be a stored XSS
                # vector if ever rendered in an <img src> or <a href>.
                raise BadRequestException(
                    detail="profile_image_url must be an absolute http(s) URL"
                )
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
        raise BaseAPIException(
            detail="Internal server error occurred while updating user"
        ) from None


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


async def update_user_location(
    db: AsyncSession, user_id: int, latitude: float, longitude: float
) -> User | None:
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
        logger.error(
            "Failed to update notification settings for user %s: %s",
            user_id,
            e,
            exc_info=True,
        )
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
        logger.error(
            "Failed to update privacy settings for user %s: %s",
            user_id,
            e,
            exc_info=True,
        )
        raise
