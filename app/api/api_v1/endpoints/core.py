from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.core.database import get_db
from app.core.config import settings
from app.core.cache import CacheKeyPatterns, cached, invalidate_cache
from app.api.api_v1.dependencies.auth import get_current_active_user, get_current_admin
from app.models.enums import UserRole
from app.schemas.user import User as UserSchema
from app.schemas.core import (
    BugReportCreate, BugReportUpdate, BugReportResponse,
    PageCreate, PageUpdate, PageResponse, PagePublicResponse,
    AppVersionCreate, AppVersionUpdate, AppVersionResponse,
    AppVersionCheckRequest, AppVersionCheckResponse,
    FAQCreate, FAQUpdate, FAQResponse
)
from app.schemas.common import MessageResponse, PaginatedResponse
from app.services.core import CoreService
from app.services.storage import storage_service

router = APIRouter()

# Dependency to get core service
def get_core_service(db: AsyncSession = Depends(get_db)) -> CoreService:
    return CoreService(db)


# Cached helper functions for public endpoints
@cached("faqs:public", ttl=settings.CACHE_TTL_FAQS)
async def get_faqs_public_cached(
    core_service: CoreService,
    category: Optional[str],
    limit: int,
    offset: int
):
    """Cached version of public FAQs listing."""
    return await core_service.get_faqs(
        category=category,
        is_active=True,
        limit=limit,
        offset=offset,
    )


@cached("versions:check", ttl=3600)  # 1 hour TTL
async def check_for_updates_cached(
    core_service: CoreService,
    app: str,
    platform: str,
    current_version: str
):
    """Cached version of app version check."""
    from app.schemas.core import AppVersionCheckRequest
    check_data = AppVersionCheckRequest(
        app=app,
        platform=platform,
        current_version=current_version
    )
    return await core_service.check_for_updates(check_data)

# ============================================================================
# BUG REPORT ENDPOINTS
# ============================================================================

@router.post("/bugs", response_model=BugReportResponse)
async def create_bug_report(
    bug_data: BugReportCreate,
    current_user: Optional[UserSchema] = Depends(get_current_active_user),
    core_service: CoreService = Depends(get_core_service)
):
    """Create a new bug report"""
    user_id = current_user.id if current_user else None
    return await core_service.create_bug_report(bug_data, user_id)

@router.post("/bugs/with-media", response_model=BugReportResponse)
async def create_bug_report_with_media(
    source: str = Form(...),
    bug_type: str = Form(...),
    severity: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    steps_to_reproduce: Optional[str] = Form(None),
    expected_behavior: Optional[str] = Form(None),
    actual_behavior: Optional[str] = Form(None),
    device_info: Optional[str] = Form(None),  # JSON string
    app_version: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),  # JSON string
    files: List[UploadFile] = File(...),
    current_user: Optional[UserSchema] = Depends(get_current_active_user),
    core_service: CoreService = Depends(get_core_service)
):
    """Create a bug report with media uploads"""
    import json

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
            print(f"Failed to upload file {file.filename}: {str(e)}")
            continue

    # Create bug report data
    bug_data = BugReportCreate(
        source=source,
        bug_type=bug_type,
        severity=severity,
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

@router.get("/bugs", response_model=List[BugReportResponse])
async def get_bug_reports(
    status: Optional[str] = Query(None, description="Filter by bug status"),
    bug_type: Optional[str] = Query(None, description="Filter by bug type"),
    limit: int = Query(20, ge=1, le=100, description="Number of results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: UserSchema = Depends(get_current_active_user),
    core_service: CoreService = Depends(get_core_service)
):
    """Get bug reports (filtered by current user if not admin)"""
    from app.models.enums import BugStatus, BugType

    # Validate and coerce enums, return 400 on invalid values
    try:
        status_enum = BugStatus(status) if status else None
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid bug status")
    try:
        bug_type_enum = BugType(bug_type) if bug_type else None
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid bug type")

    # If not admin, only show user's own bug reports
    if current_user.role != UserRole.admin.value:
        user_id = current_user.id
    else:
        user_id = None

    return await core_service.get_bug_reports(
        user_id=user_id,
        status=status_enum,
        bug_type=bug_type_enum,
        limit=limit,
        offset=offset
    )

@router.get("/bugs/{bug_id}", response_model=BugReportResponse)
async def get_bug_report(
    bug_id: int,
    current_user: UserSchema = Depends(get_current_active_user),
    core_service: CoreService = Depends(get_core_service)
):
    """Get a specific bug report"""
    bug_report = await core_service.get_bug_report_by_id(bug_id)

    # Check permissions - users can only see their own bugs unless they're admin
    if current_user.role != UserRole.admin.value and bug_report.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this bug report")

    return bug_report

@router.put("/bugs/{bug_id}", response_model=BugReportResponse)
async def update_bug_report(
    bug_id: int,
    update_data: BugReportUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
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

@router.post("/pages", response_model=PageResponse)
async def create_page(
    page_data: PageCreate,
    current_user: UserSchema = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Create a new page (admin only)"""
    return await core_service.create_page(page_data, current_user.id)

@router.get("/pages", response_model=List[PageResponse])
async def get_pages(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    is_draft: Optional[bool] = Query(None, description="Filter by draft status"),
    limit: int = Query(20, ge=1, le=100, description="Number of results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: UserSchema = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Get pages (admin only)"""
    return await core_service.get_pages(
        is_active=is_active,
        is_draft=is_draft,
        limit=limit,
        offset=offset
    )

@router.get("/pages/{unique_name}", response_model=PageResponse)
async def get_page(
    unique_name: str,
    current_user: UserSchema = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Get a specific page by unique name (admin only)"""
    page = await core_service.get_page_by_unique_name(unique_name)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page

@router.get("/pages/{unique_name}/public", response_model=PagePublicResponse)
async def get_page_public(unique_name: str, core_service: CoreService = Depends(get_core_service)):
    """Get a page for public access (no auth required)"""
    page = await core_service.get_page_public(unique_name)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page

@router.put("/pages/{unique_name}", response_model=PageResponse)
async def update_page(
    unique_name: str,
    update_data: PageUpdate,
    current_user: UserSchema = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Update a page (admin only)"""
    return await core_service.update_page(unique_name, update_data, current_user.id)

@router.delete("/pages/{unique_name}", response_model=MessageResponse)
async def delete_page(
    unique_name: str,
    current_user: UserSchema = Depends(get_current_admin),
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

@router.post("/versions", response_model=AppVersionResponse)
@invalidate_cache([CacheKeyPatterns.VERSIONS])
async def create_app_version(
    version_data: AppVersionCreate,
    current_user: UserSchema = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Create a new app version entry (admin only). Invalidates version cache."""
    return await core_service.create_app_version(version_data)

@router.post("/versions/check", response_model=AppVersionCheckResponse)
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

@router.get("/versions", response_model=List[AppVersionResponse])
async def get_app_versions(
    app: Optional[str] = Query(None, description="Filter by app identifier"),
    platform: Optional[str] = Query(None, description="Filter by platform"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    limit: int = Query(10, ge=1, le=100, description="Number of results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: UserSchema = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Get app versions (admin only)"""
    return await core_service.get_app_versions(
        app=app,
        platform=platform,
        is_active=is_active,
        limit=limit,
        offset=offset
    )

@router.put("/versions/{version_id}", response_model=AppVersionResponse)
@invalidate_cache([CacheKeyPatterns.VERSIONS])
async def update_app_version(
    version_id: int,
    update_data: AppVersionUpdate,
    current_user: UserSchema = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Update an app version entry (admin only). Invalidates version cache."""
    return await core_service.update_app_version(version_id, update_data)

# ============================================================================
# FAQ ENDPOINTS
# ============================================================================

@router.post("/faqs", response_model=FAQResponse)
@invalidate_cache([CacheKeyPatterns.FAQS])
async def create_faq(
    faq_data: FAQCreate,
    current_user: UserSchema = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Create a new FAQ (admin only). Invalidates FAQ cache."""
    return await core_service.create_faq(faq_data)

@router.get("/faqs", response_model=List[FAQResponse])
async def get_faqs_admin(
    category: Optional[str] = Query(None, description="Filter by category/platform"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    limit: int = Query(50, ge=1, le=100, description="Number of results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: UserSchema = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Get FAQs with admin filters (admin only)"""
    return await core_service.get_faqs(
        category=category,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )

@router.get("/faqs/public", response_model=List[FAQResponse])
async def get_faqs_public(
    category: Optional[str] = Query(None, description="Filter by category/platform"),
    limit: int = Query(50, ge=1, le=100, description="Number of results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    core_service: CoreService = Depends(get_core_service)
):
    """Public FAQs listing (only active FAQs, cached 6hrs)."""
    return await get_faqs_public_cached(core_service, category, limit, offset)

@router.get("/faqs/{faq_id}", response_model=FAQResponse)
async def get_faq(
    faq_id: int,
    current_user: UserSchema = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Get a specific FAQ (admin only)"""
    return await core_service.get_faq_by_id(faq_id)

@router.put("/faqs/{faq_id}", response_model=FAQResponse)
@invalidate_cache([CacheKeyPatterns.FAQS])
async def update_faq(
    faq_id: int,
    update_data: FAQUpdate,
    current_user: UserSchema = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Update an FAQ (admin only). Invalidates FAQ cache."""
    return await core_service.update_faq(faq_id, update_data)

@router.delete("/faqs/{faq_id}", response_model=MessageResponse)
@invalidate_cache([CacheKeyPatterns.FAQS])
async def delete_faq(
    faq_id: int,
    current_user: UserSchema = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service)
):
    """Soft delete an FAQ (admin only). Invalidates FAQ cache."""
    success = await core_service.delete_faq(faq_id)
    if not success:
        raise HTTPException(status_code=404, detail="FAQ not found")
    return MessageResponse(message="FAQ deleted successfully")
