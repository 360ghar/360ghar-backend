"""Admin moderation endpoints for the flatmates module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.enums import (
    ListingModerationStatus,
    ModerationAction,
    PropertyPurpose,
    PropertyType,
    ReportAction,
    UserReportStatus,
)
from app.models.properties import Property
from app.models.social import UserReport
from app.models.users import User
from app.schemas.flatmates import ListingModerationAction, ReportModerationAction
from app.schemas.flatmates_admin import (
    serialize_flatmate_listing as _serialize_flatmate_listing,
)
from app.schemas.flatmates_admin import serialize_report as _serialize_report
from app.schemas.pagination import (
    CursorParams,
    build_cursor_page,
    keyset_filter,
    keyset_payload,
    keyset_sort_value,
)
from app.services.flatmates import pause_expired_flatmate_listings, prescreen_flatmate_listing

logger = get_logger(__name__)

router = APIRouter()

FLATMATE_LISTING_TYPES = (PropertyType.flatmate, PropertyType.pg)


def _is_admin_user(user: User) -> bool:
    return getattr(user, "role", None) == "admin"


def _listing_moderation_status_expr():
    return func.coalesce(
        Property.listing_preferences["moderation_status"].as_string(),
        "pending_review",
    )


def _flatmate_listing_filters(status: str):
    return (
        Property.property_type.in_(FLATMATE_LISTING_TYPES),
        Property.purpose == PropertyPurpose.rent,
        _listing_moderation_status_expr() == status,
    )


async def _dispatch_moderation_notification(
    db: AsyncSession,
    *,
    recipient_db_id: int,
    title: str,
    body: str,
    type_key: str,
    deep_link: str = "/post",
) -> None:
    """Send a push notification for listing moderation events."""
    from app.services.push_notification import _dispatch

    await _dispatch(
        db,
        user_db_id=recipient_db_id,
        type_key=type_key,
        title=title,
        body=body,
        data={"route": deep_link},
        deep_link=deep_link,
    )


@router.get("/moderation/listings", summary="List pending listings")
async def get_pending_listings(
    status: str = Query(default="pending_review", description="Filter by status"),
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get listings pending moderation review. Requires admin role."""
    if not _is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    await pause_expired_flatmate_listings(db)

    cursor_payload: dict[str, Any] = page.decoded()
    base_stmt = (
        select(Property)
        .options(selectinload(Property.images), selectinload(Property.owner))
        .where(*_flatmate_listing_filters(status))
    )
    count_total: int | None = None
    if page.include_total:
        count_result = await db.execute(
            select(func.count()).select_from(Property).where(*_flatmate_listing_filters(status))
        )
        count_total = count_result.scalar_one()
    predicate = keyset_filter(Property.created_at, Property.id, cursor_payload, descending=False)
    if predicate is not None:
        base_stmt = base_stmt.where(predicate)
    stmt = base_stmt.order_by(Property.created_at.asc(), Property.id.asc()).limit(page.limit + 1)
    listings = list((await db.execute(stmt)).scalars().all())
    next_payload: dict[str, Any] | None = None
    if len(listings) > page.limit:
        listings = listings[:page.limit]
        next_payload = keyset_payload(
            keyset_sort_value(listings[-1].created_at), listings[-1].id
        )

    return build_cursor_page(
        [_serialize_flatmate_listing(listing) for listing in listings],
        limit=page.limit,
        next_payload=next_payload,
        total=count_total,
    )


@router.put("/moderation/listings/{listing_id}", summary="Moderate listing")
async def moderate_listing(
    listing_id: int,
    payload: ListingModerationAction,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Moderate a listing: approve, reject, or request edit. Requires admin role."""
    if not _is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    action = payload.action
    reason = payload.reason

    result = await db.execute(
        select(Property).where(
            Property.id == listing_id,
            Property.property_type.in_(FLATMATE_LISTING_TYPES),
            Property.purpose == PropertyPurpose.rent,
        )
    )
    listing = result.scalar_one_or_none()

    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    status_map: dict[ModerationAction, ListingModerationStatus] = {
        ModerationAction.approve: ListingModerationStatus.live,
        ModerationAction.reject: ListingModerationStatus.rejected,
        ModerationAction.request_edit: ListingModerationStatus.pending_review,
    }
    moderation_status = status_map[ModerationAction(payload.action)].value
    listing.is_available = payload.action == "approve"

    preferences = (
        dict(listing.listing_preferences) if isinstance(listing.listing_preferences, dict) else {}
    )
    moderated_at = datetime.now(timezone.utc)
    approval_boost_granted = False
    preferences["moderation_status"] = moderation_status
    preferences["moderated_by"] = current_user.id
    preferences["moderated_at"] = moderated_at.isoformat()
    if reason:
        preferences["moderation_reason"] = reason
    if payload.action == "approve" and not preferences.get("approval_boost_granted_at"):
        approval_boost_granted = True
        preferences["first_approved_at"] = moderated_at.isoformat()
        preferences["approval_boost_granted_at"] = moderated_at.isoformat()
        preferences["boosted_until"] = (moderated_at + timedelta(hours=24)).isoformat()
        preferences["boost_reason"] = "first_approval"
    listing.listing_preferences = preferences

    await db.commit()
    await db.refresh(listing)

    # --- SSE event to listing owner ---
    try:
        from app.core.sse import SSE_PROPERTY_UPDATE, sse_bus

        await sse_bus.emit(
            listing.owner_id,
            {
                "type": SSE_PROPERTY_UPDATE,
                "data": {
                    "property_id": listing.id,
                    "change_type": moderation_status,
                },
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning("SSE emit for listing_status_changed failed (best-effort)")

    from app.services.push_notification import notify_listing_approved

    if payload.action == "approve":
        await notify_listing_approved(
            db,
            recipient_db_id=listing.owner_id,
            listing_title=listing.title or "Your listing",
            boosted_for_hours=24 if approval_boost_granted else None,
        )
    elif payload.action == "reject":
        await _dispatch_moderation_notification(
            db,
            recipient_db_id=listing.owner_id,
            title="Listing Rejected",
            body=f'Your listing "{listing.title or "Your listing"}" was not approved.'
            + (f" Reason: {reason}" if reason else ""),
            type_key="flatmate_listing_rejected",
            deep_link="/post",
        )

    return {
        "listing_id": listing_id,
        "action": action,
        "status": moderation_status,
        "reason": reason,
    }


@router.get("/moderation/reports", summary="List pending reports")
async def get_pending_reports(
    status: str = Query(default="open", description="Filter by status"),
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get user reports pending review. Requires admin role."""
    if not _is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    cursor_payload: dict[str, Any] = page.decoded()
    base_stmt = select(UserReport).where(UserReport.status == status)
    count_total: int | None = None
    if page.include_total:
        count_result = await db.execute(
            select(func.count()).select_from(UserReport).where(UserReport.status == status)
        )
        count_total = count_result.scalar_one()
    predicate = keyset_filter(UserReport.created_at, UserReport.id, cursor_payload, descending=False)
    if predicate is not None:
        base_stmt = base_stmt.where(predicate)
    stmt = base_stmt.order_by(UserReport.created_at.asc(), UserReport.id.asc()).limit(page.limit + 1)
    reports = list((await db.execute(stmt)).scalars().all())
    next_payload: dict[str, Any] | None = None
    if len(reports) > page.limit:
        reports = reports[:page.limit]
        next_payload = keyset_payload(
            keyset_sort_value(reports[-1].created_at), reports[-1].id
        )

    user_ids = {
        uid
        for report in reports
        for uid in (report.reporter_user_id, report.reported_user_id)
    }
    user_map: dict[int, User] = {}
    if user_ids:
        users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        user_map = {user.id: user for user in users}

    return build_cursor_page(
        [_serialize_report(report, user_map) for report in reports],
        limit=page.limit,
        next_payload=next_payload,
        total=count_total,
    )


@router.put("/moderation/reports/{report_id}", summary="Moderate report")
async def moderate_report(
    report_id: int,
    payload: ReportModerationAction,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Moderate a user report. Requires admin role."""
    if not _is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    action = payload.action
    notes = payload.notes

    result = await db.execute(select(UserReport).where(UserReport.id == report_id))
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    report_status_map: dict[ReportAction, str] = {
        ReportAction.dismiss: "dismissed",
        ReportAction.warn_user: "actioned",
        ReportAction.suspend_user: "actioned",
        ReportAction.escalate: "reviewed",
    }
    report.status = UserReportStatus(report_status_map[ReportAction(payload.action)])
    if notes:
        report.notes = notes

    from app.services.push_notification import _dispatch

    if payload.action == "suspend_user":
        reported_user = await db.execute(select(User).where(User.id == report.reported_user_id))
        user = reported_user.scalar_one_or_none()
        if user:
            user.is_active = False

    await db.flush()
    await db.commit()
    await db.refresh(report)

    if payload.action == "suspend_user":
        await _dispatch(
            db,
            user_db_id=report.reported_user_id,
            type_key="flatmate_account_suspended",
            title="Account Suspended",
            body="Your account has been suspended due to a policy violation.",
            data={"route": "/profile"},
            deep_link="/profile",
        )
        await _dispatch(
            db,
            user_db_id=report.reporter_user_id,
            type_key="flatmate_report_actioned",
            title="Report Actioned",
            body="We've taken action on your report. Thank you for keeping the community safe.",
            data={"route": "/chats"},
            deep_link="/chats",
        )
    elif payload.action == "warn_user":
        await _dispatch(
            db,
            user_db_id=report.reported_user_id,
            type_key="flatmate_account_warned",
            title="Account Warning",
            body="You've received a warning regarding your behaviour. Please review our community guidelines.",
            data={"route": "/profile"},
            deep_link="/profile",
        )
        await _dispatch(
            db,
            user_db_id=report.reporter_user_id,
            type_key="flatmate_report_actioned",
            title="Report Actioned",
            body="We've reviewed your report and issued a warning. Thank you for keeping the community safe.",
            data={"route": "/chats"},
            deep_link="/chats",
        )
    elif payload.action == "dismiss":
        await _dispatch(
            db,
            user_db_id=report.reporter_user_id,
            type_key="flatmate_report_dismissed",
            title="Report Dismissed",
            body="We've reviewed your report and found no policy violation at this time.",
            data={"route": "/chats"},
            deep_link="/chats",
        )

    return {
        "report_id": report_id,
        "action": action,
        "status": report.status,
        "notes": notes,
    }


@router.post("/moderation/prescreen/{listing_id}", summary="Prescreen listing")
async def prescreen_listing(
    listing_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Run deterministic AI pre-screening for a flatmates listing. Requires admin role."""
    if not _is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return await prescreen_flatmate_listing(
        db,
        listing_id,
        admin_user_id=current_user.id,
    )
