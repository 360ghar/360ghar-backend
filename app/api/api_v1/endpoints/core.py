from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user, get_current_admin
from app.config import settings
from app.core.cache import CacheKeyPatterns, cached, invalidate_cache
from app.core.database import get_db
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.common import MessageResponse
from app.schemas.core import (
    AppVersionCheckRequest,
    AppVersionCheckResponse,
    AppVersionCreate,
    AppVersionResponse,
    AppVersionUpdate,
    BugReportCreate,
    BugReportResponse,
    BugReportUpdate,
    FAQCreate,
    FAQResponse,
    FAQUpdate,
    PageCreate,
    PagePublicResponse,
    PageResponse,
    PageUpdate,
)
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.services.core import CoreService
from app.services.storage import storage_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Dependency to get core service
def get_core_service(db: AsyncSession = Depends(get_db)) -> CoreService:
    return CoreService(db)


# Cached helper functions for public endpoints
@cached("faqs:public", ttl=settings.CACHE_TTL_FAQS)
async def get_faqs_public_cached(
    core_service: CoreService,
    category: str | None,
    limit: int,
    cursor_payload: dict,
):
    """Cached version of public FAQs listing."""
    return await core_service.get_faqs(
        category=category,
        is_active=True,
        limit=limit,
        cursor_payload=cursor_payload,
        with_total=False,
    )


@cached("versions:check", ttl=3600)  # 1 hour TTL
async def check_for_updates_cached(
    core_service: CoreService,
    app: str,
    platform: str,
    current_version: str
):
    """Cached version of app version check."""
    check_data = AppVersionCheckRequest(
        app=app,
        platform=platform,
        current_version=current_version,
        build_number=None,
    )
    return await core_service.check_for_updates(check_data)

# ============================================================================
# BUG REPORT ENDPOINTS
# ============================================================================

@router.post("/bugs", response_model=BugReportResponse, summary="Create bug report")
async def create_bug_report(
    bug_data: BugReportCreate,
    current_user: User | None = Depends(get_current_active_user),
    core_service: CoreService = Depends(get_core_service)
):
    """Create a new bug report"""
    user_id = current_user.id if current_user else None
    return await core_service.create_bug_report(bug_data, user_id)

@router.post("/bugs/with-media", response_model=BugReportResponse, summary="Create bug report with media")
async def create_bug_report_with_media(
    source: str = Form(...),
    bug_type: str = Form(...),
    severity: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    steps_to_reproduce: str | None = Form(None),
    expected_behavior: str | None = Form(None),
    actual_behavior: str | None = Form(None),
    device_info: str | None = Form(None),  # JSON string
    app_version: str | None = Form(None),
    tags: str | None = Form(None),  # JSON string
    files: list[UploadFile] = File(...),
    current_user: User | None = Depends(get_current_active_user),
    core_service: CoreService = Depends(get_core_service)
):
    """Create a bug report with media uploads"""
    import json

    from app.models.enums import BugSeverity, BugType

    # Parse JSON fields
    device_info_parsed = json.loads(device_info) if device_info else None
    tags_parsed = json.loads(tags) if tags else None

    # Upload media files
    media_urls = []
    # Use current user's ID for user-scoped paths (or skip scoping for anonymous)
    uploader_id = current_user.id if current_user else None
    for file in files:
        try:
            upload_result = await storage_service.upload_generic(file, user_id=uploader_id)
            # Storage service returns 'public_url'
            media_urls.append(upload_result["public_url"])
        except Exception as e:
            # Log error but continue with other files
            logger.error("Failed to upload file %s: %s", file.filename, e)
            continue

    # Create bug report data
    bug_data = BugReportCreate(
        source=source,
        bug_type=BugType(bug_type),
        severity=BugSeverity(severity),
        title=title,
        description=description,
        steps_to_reproduce=steps_to_reproduce,
        expected_behavior=expected_behavior,
        actual_behavior=actual_behavior,
        device_info=device_info_parsed,
        app_version=app_version,
        media_urls=media_urls if media_urls else None,
        tags=tags_parsed
    )

    user_id = current_user.id if current_user else None
    return await core_service.create_bug_report(bug_data, user_id)

@router.get("/bugs", response_model=CursorPage[BugReportResponse], summary="List bug reports")
async def get_bug_reports(
    status: str | None = Query(None, description="Filter by bug status"),
    bug_type: str | None = Query(None, description="Filter by bug type"),
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_active_user),
    core_service: CoreService = Depends(get_core_service)
):
    """Get bug reports (filtered by current user if not admin)"""
    from app.models.enums import BugStatus, BugType

    # Validate and coerce enums, return 400 on invalid values
    try:
        status_enum = BugStatus(status) if status else None
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid bug status") from None
    try:
        bug_type_enum = BugType(bug_type) if bug_type else None
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid bug type") from None

    # If not admin, only show user's own bug reports
    if current_user.role != UserRole.admin.value:
        user_id = current_user.id
    else:
        user_id = None

    rows, next_payload, total = await core_service.get_bug_reports(
        user_id=user_id,
        status=status_enum,
        bug_type=bug_type_enum,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [BugReportResponse.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )

@router.get("/bugs/{bug_id}", response_model=BugReportResponse, summary="Get bug report")
async def get_bug_report(
    bug_id: int,
    current_user: User = Depends(get_current_active_user),
    core_service: CoreService = Depends(get_core_service)
):
    """Get a specific bug report"""
    bug_report = await core_service.get_bug_report_by_id(bug_id)

    # Check permissions - users can only see their own bugs unless they're admin
    if current_user.role != UserRole.admin.value and bug_report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this bug report")

    return bug_report

@router.put("/bugs/{bug_id}", response_model=BugReportResponse, summary="Update bug report")
async def update_bug_report(
    bug_id: int,
    update_data: BugReportUpdate,
    current_user: User = Depends(get_current_active_user),
    core_service: CoreService = Depends(get_core_service)
):
    """Update a bug report (admin only for status updates)"""
    # Check if user can update this bug report
    bug_report = await core_service.get_bug_report_by_id(bug_id)

    # Only allow status and assignment updates for non-admin users
    if current_user.role != UserRole.admin.value:
        if bug_report.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to update this bug report")

        # Non-admin users can only update certain fields
        allowed_fields = {'resolution'} if update_data.resolution else set()
        update_dict = update_data.model_dump(exclude_unset=True)
        if not all(field in allowed_fields for field in update_dict.keys()):
            raise HTTPException(status_code=403, detail="Not authorized to update these fields")

    return await core_service.update_bug_report(bug_id, update_data, current_user.id)

# ============================================================================
# PAGE ENDPOINTS
# ============================================================================

@router.post("/pages", response_model=PageResponse, summary="Create page")
async def create_page(
    page_data: PageCreate,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Create a new page (admin only)"""
    return await core_service.create_page(page_data, current_user.id)

@router.get("/pages", response_model=CursorPage[PageResponse], summary="List pages")
async def get_pages(
    is_active: bool | None = Query(None, description="Filter by active status"),
    is_draft: bool | None = Query(None, description="Filter by draft status"),
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Get pages (admin only)"""
    rows, next_payload, total = await core_service.get_pages(
        is_active=is_active,
        is_draft=is_draft,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [PageResponse.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )

@router.get("/pages/{unique_name}", response_model=PageResponse, summary="Get page")
async def get_page(
    unique_name: str,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Get a specific page by unique name (admin only)"""
    page = await core_service.get_page_by_unique_name(unique_name)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page

@router.get("/pages/{unique_name}/public", response_model=PagePublicResponse, summary="Get public page")
async def get_page_public(unique_name: str, core_service: CoreService = Depends(get_core_service)):
    """Get a page for public access (no auth required)"""
    page = await core_service.get_page_public(unique_name)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page

@router.put("/pages/{unique_name}", response_model=PageResponse, summary="Update page")
async def update_page(
    unique_name: str,
    update_data: PageUpdate,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Update a page (admin only)"""
    return await core_service.update_page(unique_name, update_data, current_user.id)

@router.delete("/pages/{unique_name}", response_model=MessageResponse, summary="Delete page")
async def delete_page(
    unique_name: str,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Delete a page (admin only)"""
    success = await core_service.delete_page(unique_name)
    if not success:
        raise HTTPException(status_code=404, detail="Page not found")

    return MessageResponse(message="Page deleted successfully")

# ============================================================================
# APP VERSION ENDPOINTS
# ============================================================================

@router.post("/versions", response_model=AppVersionResponse, summary="Create app version")
@invalidate_cache([CacheKeyPatterns.VERSIONS])
async def create_app_version(
    version_data: AppVersionCreate,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Create a new app version entry (admin only). Invalidates version cache."""
    return await core_service.create_app_version(version_data)

@router.post("/versions/check", response_model=AppVersionCheckResponse, summary="Check for app updates")
async def check_for_updates(
    check_data: AppVersionCheckRequest,
    core_service: CoreService = Depends(get_core_service)
):
    """Check if there's an available update (public endpoint, cached 1hr)."""
    return await check_for_updates_cached(
        core_service,
        check_data.app,
        check_data.platform,
        check_data.current_version
    )

@router.get("/versions", response_model=CursorPage[AppVersionResponse], summary="List app versions")
async def get_app_versions(
    app: str | None = Query(None, description="Filter by app identifier"),
    platform: str | None = Query(None, description="Filter by platform"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Get app versions (admin only)"""
    rows, next_payload, total = await core_service.get_app_versions(
        app=app,
        platform=platform,
        is_active=is_active,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(rows, limit=page.limit, next_payload=next_payload, total=total)

@router.put("/versions/{version_id}", response_model=AppVersionResponse, summary="Update app version")
@invalidate_cache([CacheKeyPatterns.VERSIONS])
async def update_app_version(
    version_id: int,
    update_data: AppVersionUpdate,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Update an app version entry (admin only). Invalidates version cache."""
    return await core_service.update_app_version(version_id, update_data)

# ============================================================================
# FAQ ENDPOINTS
# ============================================================================

@router.post("/faqs", response_model=FAQResponse, summary="Create FAQ")
@invalidate_cache([CacheKeyPatterns.FAQS])
async def create_faq(
    faq_data: FAQCreate,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Create a new FAQ (admin only). Invalidates FAQ cache."""
    return await core_service.create_faq(faq_data)

@router.get("/faqs", response_model=CursorPage[FAQResponse], summary="List FAQs (admin)")
async def get_faqs_admin(
    category: str | None = Query(None, description="Filter by category/platform"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Get FAQs with admin filters (admin only)"""
    rows, next_payload, total = await core_service.get_faqs(
        category=category,
        is_active=is_active,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [FAQResponse.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )

@router.get("/faqs/public", response_model=CursorPage[FAQResponse], summary="List FAQs (public)")
async def get_faqs_public(
    category: str | None = Query(None, description="Filter by category/platform"),
    page: CursorParams = Depends(),
    core_service: CoreService = Depends(get_core_service)
):
    """Public FAQs listing (only active FAQs, cached 6hrs)."""
    rows, next_payload, total = await get_faqs_public_cached(
        core_service,
        category=category,
        limit=page.limit,
        cursor_payload=page.decoded(),
    )
    return build_cursor_page(
        [FAQResponse.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )

@router.get("/faqs/{faq_id}", response_model=FAQResponse, summary="Get FAQ")
async def get_faq(
    faq_id: int,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Get a specific FAQ (admin only)"""
    return await core_service.get_faq_by_id(faq_id)

@router.put("/faqs/{faq_id}", response_model=FAQResponse, summary="Update FAQ")
@invalidate_cache([CacheKeyPatterns.FAQS])
async def update_faq(
    faq_id: int,
    update_data: FAQUpdate,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Update an FAQ (admin only). Invalidates FAQ cache."""
    return await core_service.update_faq(faq_id, update_data)

@router.delete("/faqs/{faq_id}", response_model=MessageResponse, summary="Delete FAQ")
@invalidate_cache([CacheKeyPatterns.FAQS])
async def delete_faq(
    faq_id: int,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Soft delete an FAQ (admin only). Invalidates FAQ cache."""
    success = await core_service.delete_faq(faq_id)
    if not success:
        raise HTTPException(status_code=404, detail="FAQ not found")
    return MessageResponse(message="FAQ deleted successfully")
