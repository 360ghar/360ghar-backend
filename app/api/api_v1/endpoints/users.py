from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_admin,
)
from app.core.database import get_db
from app.core.exceptions import (
    BadRequestException,
    BaseAPIException,
    ForbiddenException,
    NotFoundException,
)
from app.core.logging import get_logger
from app.models.enums import AppKey, UserRole
from app.models.users import User
from app.schemas.common import (
    AssignAgentPayload,
    NotificationSettings,
    NotificationSettingsWrite,
    PrivacySettings,
    PrivacySettingsPatch,
)
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.user import (
    AdminUser,
    AdminUserUpdate,
    AuthGateState,
    LocationUpdate,
    PhoneUpdate,
    SelfUser,
    UserLocation,
    UserPreferences,
    UserPreferencesPatch,
    UserUpdate,
)
from app.services.agent import assign_agent_to_user
from app.services.storage import storage_service
from app.services.user import (
    complete_app_onboarding,
    compute_auth_gate_state,
    delete_user_account,
    get_all_users,
    get_user_by_id,
    read_preferences,
    read_typed_blob,
    update_user,
    update_user_location,
    update_user_notification_settings,
    update_user_preferences,
    update_user_privacy_settings,
)

logger = get_logger(__name__)

router = APIRouter()


@router.get("/me", response_model=SelfUser, summary="Get current user")
async def get_user_me(current_user: User = Depends(get_current_active_user)):
    """Get current user profile (alias for /profile)."""
    return SelfUser.model_validate(current_user)


@router.get("/me/auth-state", response_model=AuthGateState, summary="Get current user auth state")
async def get_auth_state(
    app: AppKey = Query(AppKey.flatmates, description="App key for the onboarding check"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Compute and return the current auth gate stage for the user.

    Returns the centralized gate state:
      ``stage``: one of identifier_verification, password_setup,
        profile_completion, app_onboarding, active
      ``next_action``: what the client should route to
      ``missing_fields``: profile fields still required (if applicable)

    The ``app`` query param selects which app's onboarding check to run
    (defaults to ``flatmates``).  New apps register their check via
    :func:`register_app_onboarding_check` during startup.
    """
    return await compute_auth_gate_state(db, current_user, app=app.value)


@router.post("/me/onboarding", response_model=SelfUser, summary="Complete user onboarding")
async def complete_onboarding(
    app: AppKey = Query(..., description="App key whose onboarding to complete"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark the given app's onboarding as complete.

    Sets ``<app>_onboarding_completed = True`` on the current user so the gate
    advances past ``app_onboarding`` on subsequent ``GET /me/auth-state`` calls.
    """
    updated = await complete_app_onboarding(db, current_user, app=app.value)
    return SelfUser.model_validate(updated)


@router.delete("/me", status_code=204, summary="Delete my account")
async def delete_my_account(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete the current user's account.

    Hard-deletes the Supabase Auth user (revoking all sessions) and
    anonymizes + soft-deletes the local record. This is the canonical account
    deletion route. ``POST /auth/delete-account`` is an alias kept until the
    clients move. Returns 204 with no body.
    """
    try:
        await delete_user_account(db, current_user)
    except (BaseAPIException, HTTPException):
        raise
    except Exception as exc:
        logger.error(
            "Unexpected delete account failure for user %s: %s",
            current_user.id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error. Please try again later.",
        ) from None
    return Response(status_code=204)


@router.put("/me", response_model=SelfUser, summary="Update current user")
async def update_user_me(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user profile (alias for /profile)."""
    updated_user = await update_user(db, current_user.id, user_update, actor=current_user)
    if not updated_user:
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    return SelfUser.model_validate(updated_user)


@router.put("/me/phone", response_model=SelfUser, summary="Update current user phone")
async def update_user_phone(
    phone_update: PhoneUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's phone number. Phone is saved but NOT verified.

    Changing the phone resets ``phone_verified`` (the new number must be
    confirmed via OTP before it is trusted).  ``phone_verified`` is intentionally
    not a field on :class:`UserUpdate` (it must never be client-settable), so we
    apply it directly on the user row after the update.
    """
    user_update = UserUpdate(phone=phone_update.phone)
    updated_user = await update_user(db, current_user.id, user_update, actor=current_user)
    if not updated_user:
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    return SelfUser.model_validate(updated_user)


async def _upload_avatar(
    file: UploadFile,
    current_user: User,
    db: AsyncSession,
) -> SelfUser:
    """Shared logic for avatar upload with WebP conversion.

    Uses ``storage_service.upload_user_avatar()`` which routes through
    ``upload_with_path(folder=AVATAR)`` — that already calls
    ``image_processing.optimize_for_web(max_dimension=512, quality=85)``
    to convert the image to WebP and downscale before uploading to storage.
    """
    result = await storage_service.upload_user_avatar(
        file,
        user_id=current_user.id,
        db=db,
    )

    new_url = result["public_url"]
    old_url = current_user.profile_image_url

    # Update the user's profile_image_url
    current_user.profile_image_url = new_url
    await db.flush()
    await db.refresh(current_user)

    # Delete old avatar from storage if it existed and is different
    if old_url and old_url != new_url:
        try:
            old_path = storage_service.extract_path_from_url(old_url)
            if old_path:
                storage_service.delete_file(old_path)
        except Exception:
            logger.warning("Failed to delete old avatar for user %s", current_user.id)

    return SelfUser.model_validate(current_user)


@router.post("/me/avatar", response_model=SelfUser, summary="Upload user avatar")
async def upload_user_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a profile avatar image.

    The image is automatically converted to WebP and downscaled to
    512 px max dimension at quality 85 before storage, saving
    bandwidth and storage costs.

    Returns the updated user profile with the new ``profile_image_url``.
    """
    return await _upload_avatar(file, current_user, db)


@router.post("/me/profile-image", response_model=SelfUser, summary="Upload user profile image")
async def upload_user_profile_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a profile image (alias for /me/avatar).

    The image is automatically converted to WebP and downscaled to
    512 px max dimension at quality 85 before storage.
    """
    return await _upload_avatar(file, current_user, db)


@router.get("/profile", response_model=SelfUser, summary="Get user profile")
async def get_user_profile(current_user: User = Depends(get_current_active_user)):
    """Get current user profile"""
    return SelfUser.model_validate(current_user)


@router.put("/profile", response_model=SelfUser, summary="Update user profile")
async def update_user_profile(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user profile"""
    updated_user = await update_user(db, current_user.id, user_update, actor=current_user)
    if not updated_user:
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    return SelfUser.model_validate(updated_user)


@router.put("/preferences", response_model=UserPreferences, summary="Update user preferences")
async def update_preferences(
    preferences: UserPreferencesPatch,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user preferences. Keys not sent are kept. A key sent as null is removed."""
    updated = await update_user_preferences(
        db,
        current_user.id,
        preferences.model_dump(mode="json", exclude_unset=True),
    )
    if not updated:
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    return read_preferences(updated.preferences)


@router.put("/location", response_model=UserLocation, summary="Update user location")
async def update_location(
    location_update: LocationUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user's current location"""
    updated = await update_user_location(
        db, current_user.id, location_update.latitude, location_update.longitude
    )
    if not updated:
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    return UserLocation(
        current_latitude=updated.current_latitude,
        current_longitude=updated.current_longitude,
    )


@router.get(
    "/notification-settings",
    response_model=NotificationSettings,
    summary="Get notification settings",
)
async def get_notification_settings(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationSettings:
    """Return the current user's notification settings.

    Falls back to defaults defined in NotificationSettings when no
    explicit settings are stored.
    """
    user = await get_user_by_id(db, current_user.id)
    return read_typed_blob(NotificationSettings, user.notification_settings if user else None)


@router.put(
    "/notification-settings",
    response_model=NotificationSettings,
    summary="Update notification settings",
)
async def update_notification_settings(
    settings: NotificationSettingsWrite,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationSettings:
    """Update the current user's notification settings. Keys not sent keep their stored value."""
    user = await update_user_notification_settings(
        db,
        current_user.id,
        settings.model_dump(exclude_unset=True),
    )
    if not user:
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    return read_typed_blob(NotificationSettings, user.notification_settings)


@router.put("/notifications", response_model=NotificationSettings, summary="Update notifications")
async def update_notifications_compat(
    settings: NotificationSettingsWrite,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationSettings:
    """Compatibility endpoint for the stays app. Same body and response as PUT /users/notification-settings."""
    user = await update_user_notification_settings(
        db, current_user.id, settings.model_dump(exclude_unset=True)
    )
    if not user:
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    return read_typed_blob(NotificationSettings, user.notification_settings)


@router.get("/privacy-settings", response_model=PrivacySettings, summary="Get privacy settings")
async def get_privacy_settings(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PrivacySettings:
    """Return the current user's privacy settings."""
    user = await get_user_by_id(db, current_user.id)
    return read_typed_blob(PrivacySettings, user.privacy_settings if user else None)


@router.put("/privacy-settings", response_model=PrivacySettings, summary="Update privacy settings")
async def update_privacy_settings(
    settings: PrivacySettingsPatch,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PrivacySettings:
    """Update the current user's privacy settings. Keys not sent keep their stored value."""
    user = await update_user_privacy_settings(
        db, current_user.id, settings.model_dump(exclude_unset=True)
    )
    if not user:
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    return read_typed_blob(PrivacySettings, user.privacy_settings)


@router.put("/privacy", response_model=SelfUser, summary="Update privacy")
async def update_privacy_compat(
    settings: PrivacySettingsPatch,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SelfUser:
    """Compatibility endpoint for the stays and flatmates apps. Same typed body as PUT /users/privacy-settings."""
    user = await update_user_privacy_settings(
        db, current_user.id, settings.model_dump(exclude_unset=True)
    )
    if not user:
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    return SelfUser.model_validate(user)


# Admin/Agent management endpoints
@router.get("", response_model=CursorPage[AdminUser], summary="List users")
async def list_users(
    page: CursorParams = Depends(),
    q: str | None = Query(None, description="Search by name/email/phone"),
    agent_id: int | None = Query(None, description="Filter by agent id (admin only)"),
    unassigned: bool | None = Query(
        None, description="Admin only: only users with no assigned agent"
    ),
    is_active: bool | None = Query(None, description="Filter by active status"),
    phone_verified: bool | None = Query(None, description="Filter by phone verification status"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List users. Admins see all (optionally filter by agent). Agents see their assigned users."""
    # Resolve effective agent filter based on role
    effective_agent_id = None
    if current_user.role == UserRole.admin.value:
        effective_agent_id = agent_id
    elif current_user.role == UserRole.agent.value:
        effective_agent_id = current_user.agent_id
    else:
        raise ForbiddenException(detail="Access denied", error_code="USER_ACCESS_DENIED")

    # Unassigned is an admin-only concept (an agent's scope only ever contains
    # their own assigned users, so the flag is meaningless for agents).
    filter_unassigned = unassigned is True and current_user.role == UserRole.admin.value

    # Every filter that changes the result set. The cursor is bound to this dict.
    filters = {
        "q": q,
        "agent_id": effective_agent_id,
        "unassigned": filter_unassigned,
        "is_active": is_active,
        "phone_verified": phone_verified,
    }
    if current_user.role == UserRole.agent.value and effective_agent_id is None:
        # Agents without linked agent profile manage nobody
        return build_cursor_page(
            [], limit=page.limit, next_payload=None, total=None, filters=filters
        )

    users, next_payload, total = await get_all_users(
        db,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
        search_query=q,
        filter_agent_id=effective_agent_id,
        filter_unassigned=filter_unassigned,
        filter_is_active=is_active,
        filter_phone_verified=phone_verified,
    )
    return build_cursor_page(
        [AdminUser.model_validate(u) for u in users],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )


@router.get("/{user_id}", response_model=AdminUser, summary="Get user details")
async def get_user_details(
    user_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get user details."""
    user = await get_user_by_id(db, user_id)
    if not user:
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    # Authorization
    if current_user.role == UserRole.admin.value:
        pass
    elif current_user.role == UserRole.agent.value:
        if current_user.agent_id is None or user.agent_id != current_user.agent_id:
            raise ForbiddenException(detail="Access denied", error_code="USER_ACCESS_DENIED")
    else:
        raise ForbiddenException(detail="Access denied", error_code="USER_ACCESS_DENIED")
    return AdminUser.model_validate(user)


@router.put("/{user_id}", response_model=AdminUser, summary="Update user")
async def update_user_details(
    user_id: int,
    user_update: AdminUserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a user. Admins can update any user, including ``is_active``. Agents can update
    display and settings fields for users assigned to them."""
    updated_user = await update_user(db, user_id, user_update, actor=current_user)
    if not updated_user:
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    # Re-read with the agent loaded: AdminUser reads it, and a refreshed row does not carry it.
    reloaded = await get_user_by_id(db, user_id)
    return AdminUser.model_validate(reloaded or updated_user)


@router.post("/{user_id}/assign-agent", response_model=AdminUser, summary="Assign agent to user")
async def assign_agent_to_specific_user(
    user_id: int,
    payload: AssignAgentPayload,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Assign an agent to a user (admin only). Returns the updated user."""
    if await get_user_by_id(db, user_id) is None:
        raise NotFoundException(detail="User not found", error_code="USER_NOT_FOUND")
    assignment = await assign_agent_to_user(db, user_id, payload.agent_id)
    if not assignment:
        raise BadRequestException(detail="Agent is not available", error_code="AGENT_UNAVAILABLE")
    await db.commit()
    reloaded = await get_user_by_id(db, user_id)
    return AdminUser.model_validate(reloaded)
