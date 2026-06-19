from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import (
    get_current_active_user,
    get_current_admin,
)
from app.core.database import get_db
from app.core.exceptions import ConflictException
from app.core.logging import get_logger
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.common import (
    AssignAgentPayload,
    MessageResponse,
    NotificationSettings,
    PrivacySettings,
)
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.user import LocationUpdate, PhoneUpdate, UserPreferences, UserUpdate
from app.schemas.user import User as UserSchema
from app.services.agent import assign_agent_to_user
from app.services.storage import storage_service
from app.services.user import (
    complete_app_onboarding,
    compute_auth_gate_state,
    delete_user_account,
    get_all_users,
    get_user_by_id,
    update_user,
    update_user_location,
    update_user_notification_settings,
    update_user_preferences,
    update_user_privacy_settings,
)

logger = get_logger(__name__)

router = APIRouter()


@router.get("/me", response_model=UserSchema, summary="Get current user")
async def get_user_me(current_user: User = Depends(get_current_active_user)):
    """Get current user profile (alias for /profile)."""
    return UserSchema.model_validate(current_user)


@router.get("/me/auth-state", summary="Get current user auth state")
async def get_auth_state(
    app: str = Query("flatmates", min_length=1, description="App slug for onboarding check"),
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
    return await compute_auth_gate_state(db, current_user, app=app)


@router.post("/me/onboarding", response_model=UserSchema, summary="Complete user onboarding")
async def complete_onboarding(
    app: str = Query(..., min_length=1, description="App slug whose onboarding to complete"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark the given app's onboarding as complete.

    Sets ``<app>_onboarding_completed = True`` on the current user so the gate
    advances past ``app_onboarding`` on subsequent ``GET /me/auth-state`` calls.
    """
    updated = await complete_app_onboarding(db, current_user, app=app)
    return UserSchema.model_validate(updated)


@router.get("/me/identities", summary="List linked identities")
async def get_linked_identities(
    current_user: User = Depends(get_current_active_user),
):
    """Return the OAuth identities linked to the current Supabase user.

    Reads from the app_metadata on the current user (populated during login
    by the dependency layer).  Returns a list of ``{provider, identity_id}``.
    """
    identities = []
    # The dependency layer stores app_metadata on the User model's
    # supabase_user_id-linked auth record.  We read the raw app_metadata
    # from the current request's resolved user if available.
    raw = getattr(current_user, "_supabase_app_metadata", None)
    if isinstance(raw, dict):
        for provider, id_data in (raw.get("provider") or raw.get("providers") or {}).items():
            if isinstance(id_data, dict):
                identities.append({"provider": provider, "identity_id": id_data.get("id")})
            else:
                identities.append({"provider": provider})
    return {"identities": identities}


@router.delete("/me", response_model=MessageResponse, summary="Delete my account")
async def delete_my_account(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete the current user's account.

    Hard-deletes the Supabase Auth user (revoking all sessions) and
    anonymizes + soft-deletes the local record. Shares the same logic as
    ``POST /auth/delete-account``.
    """
    await delete_user_account(db, current_user)
    return MessageResponse(message="Account deleted successfully")


@router.put("/me", response_model=UserSchema, summary="Update current user")
async def update_user_me(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user profile (alias for /profile)."""
    updated_user = await update_user(db, current_user.id, user_update, actor=current_user)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserSchema.model_validate(updated_user)


@router.put("/me/phone", response_model=UserSchema, summary="Update current user phone")
async def update_user_phone(
    phone_update: PhoneUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's phone number. Phone is saved but NOT verified."""
    user_update = UserUpdate(phone=phone_update.phone, phone_verified=False)
    try:
        updated_user = await update_user(db, current_user.id, user_update, actor=current_user)
    except IntegrityError:
        await db.rollback()
        raise ConflictException(
            detail="Phone number is already associated with another account"
        ) from None
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserSchema.model_validate(updated_user)


async def _upload_avatar(
    file: UploadFile,
    current_user: User,
    db: AsyncSession,
) -> UserSchema:
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

    return UserSchema.model_validate(current_user)


@router.post("/me/avatar", response_model=UserSchema, summary="Upload user avatar")
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


@router.post("/me/profile-image", response_model=UserSchema, summary="Upload user profile image")
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


@router.get("/profile", response_model=UserSchema, summary="Get user profile")
async def get_user_profile(current_user: User = Depends(get_current_active_user)):
    """Get current user profile"""
    return UserSchema.model_validate(current_user)


@router.put("/profile", response_model=UserSchema, summary="Update user profile")
async def update_user_profile(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user profile"""
    updated_user = await update_user(db, current_user.id, user_update, actor=current_user)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserSchema.model_validate(updated_user)


@router.put("/preferences", response_model=MessageResponse, summary="Update user preferences")
async def update_preferences(
    preferences: UserPreferences,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user preferences"""
    await update_user_preferences(
        db,
        current_user.id,
        preferences.model_dump(mode="json", exclude_none=True),
    )
    return MessageResponse(message="Preferences updated successfully")


@router.put("/location", response_model=MessageResponse, summary="Update user location")
async def update_location(
    location_update: LocationUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user's current location"""
    await update_user_location(
        db, current_user.id, location_update.latitude, location_update.longitude
    )
    return MessageResponse(message="Location updated successfully")


@router.get("/notification-settings", response_model=NotificationSettings, summary="Get notification settings")
async def get_notification_settings(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationSettings:
    """Return the current user's notification settings.

    Falls back to defaults defined in NotificationSettings when no
    explicit settings are stored.
    """
    user = await get_user_by_id(db, current_user.id)
    # user.notification_settings is stored as JSON; merge with defaults
    raw = (user.notification_settings or {}) if user else {}
    return NotificationSettings(**raw)


@router.put("/notification-settings", response_model=MessageResponse, summary="Update notification settings")
async def update_notification_settings(
    settings: NotificationSettings,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Update the current user's notification settings (360 Ghar app)."""
    await update_user_notification_settings(
        db,
        current_user.id,
        settings.model_dump(by_alias=True, exclude_none=True),
    )
    return MessageResponse(message="Notification settings updated successfully")


@router.put("/notifications", response_model=UserSchema, summary="Update notifications")
async def update_notifications_compat(
    settings: dict,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UserSchema:
    """Compatibility endpoint for the stays app.

    Accepts an arbitrary JSON object and stores it in users.notification_settings.
    """
    user = await update_user_notification_settings(db, current_user.id, settings)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserSchema.model_validate(user)


@router.get("/privacy-settings", response_model=PrivacySettings, summary="Get privacy settings")
async def get_privacy_settings(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PrivacySettings:
    """Return the current user's privacy settings."""
    user = await get_user_by_id(db, current_user.id)
    raw = (user.privacy_settings or {}) if user else {}
    return PrivacySettings(**raw)


@router.put("/privacy-settings", response_model=MessageResponse, summary="Update privacy settings")
async def update_privacy_settings(
    settings: PrivacySettings,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Update the current user's privacy settings (360 Ghar app)."""
    await update_user_privacy_settings(db, current_user.id, settings.model_dump())
    return MessageResponse(message="Privacy settings updated successfully")


@router.put("/privacy", response_model=UserSchema, summary="Update privacy")
async def update_privacy_compat(
    settings: dict,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UserSchema:
    """Compatibility endpoint for the stays app privacy settings."""
    user = await update_user_privacy_settings(db, current_user.id, settings)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserSchema.model_validate(user)


# Admin/Agent management endpoints
@router.get("", response_model=CursorPage[UserSchema], summary="List users")
async def list_users(
    page: CursorParams = Depends(),
    q: str | None = Query(None, description="Search by name/email/phone"),
    agent_id: int | None = Query(None, description="Filter by agent id (admin only)"),
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
        if effective_agent_id is None:
            # Agents without linked agent profile manage nobody
            return build_cursor_page([], limit=page.limit, next_payload=None, total=None)
    else:
        raise HTTPException(status_code=403, detail="Access denied")

    users, next_payload, total = await get_all_users(
        db,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
        search_query=q,
        filter_agent_id=effective_agent_id,
    )
    return build_cursor_page(
        [UserSchema.model_validate(u) for u in users],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.get("/{user_id}", response_model=UserSchema, summary="Get user details")
async def get_user_details(
    user_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get user details."""
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Authorization
    if current_user.role == UserRole.admin.value:
        pass
    elif current_user.role == UserRole.agent.value:
        if current_user.agent_id is None or user.agent_id != current_user.agent_id:
            raise HTTPException(status_code=403, detail="Access denied")
    else:
        raise HTTPException(status_code=403, detail="Access denied")
    return UserSchema.model_validate(user)


@router.put("/{user_id}", response_model=UserSchema, summary="Update user")
async def update_user_details(
    user_id: int,
    user_update: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    # Admin can update any user; Agent can update limited fields for assigned users
    """Update user."""
    updated_user = await update_user(db, user_id, user_update, actor=current_user)
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserSchema.model_validate(updated_user)


@router.post("/{user_id}/assign-agent", response_model=MessageResponse, summary="Assign agent to user")
async def assign_agent_to_specific_user(
    user_id: int,
    payload: AssignAgentPayload,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Assign agent to user."""
    assignment = await assign_agent_to_user(db, user_id, payload.agent_id)
    if not assignment:
        raise HTTPException(status_code=400, detail="Failed to assign agent")
    return MessageResponse(message="Agent assigned successfully")
