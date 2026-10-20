from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user, get_current_admin
from app.config import settings
from app.core.cache import CacheKeyPatterns, cached, invalidate_cache
from app.core.database import get_db
from app.core.db_resilience import (
    extract_db_error_code,
    is_statement_timeout,
    is_transient_db_error,
)
from app.core.exceptions import ForbiddenException, NotFoundException, ServiceUnavailableException
from app.models.enums import AppKey, BugSeverity, BugStatus, BugType, DevicePlatform, UserRole
from app.models.users import User
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


@cached(
    "versions:check",
    ttl=settings.CACHE_TTL_VERSIONS,
    key_params=["app", "platform", "current_version", "build_number"],
)
async def check_for_updates_cached(
    core_service: CoreService,
    app: str,
    platform: str,
    current_version: str,
    build_number: int | None = None,
):
    """Cached version of app version check."""
    check_data = AppVersionCheckRequest(
        app=AppKey(app),
        platform=DevicePlatform(platform),
        current_version=current_version,
        build_number=build_number,
    )
    return await core_service.check_for_updates(check_data)


def _form_json(raw: str | None, field: str) -> Any:
    """Parse a JSON form field. Bad JSON is a field error, not a 500."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RequestValidationError(
            [
                {
                    "type": "json_invalid",
                    "loc": ("body", field),
                    "msg": "Input must be valid JSON",
                    "input": raw,
                }
            ]
        ) from exc


# ============================================================================
# BUG REPORT ENDPOINTS
# ============================================================================


@router.post(
    "/bugs", response_model=BugReportResponse, status_code=201, summary="Create bug report"
)
async def create_bug_report(
    bug_data: BugReportCreate,
    current_user: User = Depends(get_current_active_user),
    core_service: CoreService = Depends(get_core_service),
):
    """Create a new bug report (authenticated)"""
    return await core_service.create_bug_report(bug_data, current_user.id)


@router.post(
    "/bugs/with-media",
    response_model=BugReportResponse,
    status_code=201,
    summary="Create bug report with media",
)
async def create_bug_report_with_media(
    source: str = Form(..., min_length=1, max_length=50),
    bug_type: BugType = Form(...),
    severity: BugSeverity = Form(...),
    title: str = Form(..., min_length=1, max_length=200),
    description: str = Form(..., min_length=1),
    steps_to_reproduce: str | None = Form(None),
    expected_behavior: str | None = Form(None),
    actual_behavior: str | None = Form(None),
    device_info: str | None = Form(None, description="JSON object as a string"),
    app_version: str | None = Form(None, max_length=50),
    tags: str | None = Form(None, description="JSON array of strings as a string"),
    files: list[UploadFile] | None = File(None),
    current_user: User = Depends(get_current_active_user),
    core_service: CoreService = Depends(get_core_service),
):
    """Create a bug report with optional media uploads (authenticated).

    Enum fields are typed form fields. Invalid JSON or values return 422 in the
    shared envelope with ``details.fields``.
    """
    device_info_parsed = _form_json(device_info, "device_info")
    tags_parsed = _form_json(tags, "tags")

    # Validate every field before any upload, so a rejected report leaves no files behind.
    try:
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
            media_urls=None,
            tags=tags_parsed,
        )
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        raise RequestValidationError(
            [{**err, "loc": ("body", *err["loc"])} for err in errors]
        ) from exc

    # Upload media files
    media_urls: list[str] = []
    uploader_id = current_user.id
    for file in files or []:
        try:
            upload_result = await storage_service.upload_generic(file, user_id=uploader_id)
            # Storage service returns 'public_url'
            media_urls.append(upload_result["public_url"])
        except Exception as e:
            # Log error but continue with other files
            logger.error("Failed to upload file %s: %s", file.filename, e)
            continue

    bug_data = bug_data.model_copy(update={"media_urls": media_urls or None})

    return await core_service.create_bug_report(bug_data, current_user.id)


@router.get("/bugs", response_model=CursorPage[BugReportResponse], summary="List bug reports")
async def get_bug_reports(
    status: BugStatus | None = Query(None, description="Filter by bug status"),
    bug_type: BugType | None = Query(None, description="Filter by bug type"),
    severity: BugSeverity | None = Query(None, description="Filter by bug severity"),
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_active_user),
    core_service: CoreService = Depends(get_core_service),
):
    """Get bug reports (filtered by current user if not admin)"""
    # Invalid enum values are rejected by FastAPI with 422, matching the
    # bookings/visits list filters.

    # If not admin, only show user's own bug reports
    if current_user.role != UserRole.admin.value:
        user_id = current_user.id
    else:
        user_id = None

    # Every filter that changes the result set. The cursor is bound to this dict.
    filters = {
        "user_id": user_id,
        "status": status.value if status else None,
        "bug_type": bug_type.value if bug_type else None,
        "severity": severity.value if severity else None,
    }
    rows, next_payload, total = await core_service.get_bug_reports(
        user_id=user_id,
        status=status,
        bug_type=bug_type,
        severity=severity,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [BugReportResponse.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )


@router.put("/bugs/{bug_id}", response_model=BugReportResponse, summary="Update bug report")
async def update_bug_report(
    bug_id: int,
    update_data: BugReportUpdate,
    current_user: User = Depends(get_current_active_user),
    core_service: CoreService = Depends(get_core_service),
):
    """Update a bug report (admin only for status updates)"""
    # Check if user can update this bug report
    bug_report = await core_service.get_bug_report_by_id(bug_id)

    # Only allow status and assignment updates for non-admin users
    if current_user.role != UserRole.admin.value:
        if bug_report.user_id != current_user.id:
            raise ForbiddenException(
                detail="Not authorized to update this bug report", error_code="BUG_ACCESS_DENIED"
            )

        # Non-admin users can only update certain fields
        allowed_fields = {"resolution"} if update_data.resolution else set()
        update_dict = update_data.model_dump(exclude_unset=True)
        if not all(field in allowed_fields for field in update_dict.keys()):
            raise ForbiddenException(
                detail="Not authorized to update these fields", error_code="BUG_FIELD_FORBIDDEN"
            )

    return await core_service.update_bug_report(bug_id, update_data, current_user.id)


# ============================================================================
# PAGE ENDPOINTS
# ============================================================================


@router.post("/pages", response_model=PageResponse, status_code=201, summary="Create page")
async def create_page(
    page_data: PageCreate,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service),
):
    """Create a new page (admin only)"""
    return await core_service.create_page(page_data, current_user.id)


@router.get("/pages", response_model=CursorPage[PageResponse], summary="List pages")
async def get_pages(
    is_active: bool | None = Query(None, description="Filter by active status"),
    is_draft: bool | None = Query(None, description="Filter by draft status"),
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service),
):
    """Get pages (admin only)"""
    filters = {"is_active": is_active, "is_draft": is_draft}
    rows, next_payload, total = await core_service.get_pages(
        is_active=is_active,
        is_draft=is_draft,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [PageResponse.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )


@router.get(
    "/pages/{unique_name}/public", response_model=PagePublicResponse, summary="Get public page"
)
async def get_page_public(unique_name: str, core_service: CoreService = Depends(get_core_service)):
    """Get a page for public access (no auth required)"""
    page = await core_service.get_page_public(unique_name)
    if not page:
        raise NotFoundException(detail="Page not found", error_code="PAGE_NOT_FOUND")
    return page


@router.put("/pages/{unique_name}", response_model=PageResponse, summary="Update page")
async def update_page(
    unique_name: str,
    update_data: PageUpdate,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service),
):
    """Update a page (admin only)"""
    return await core_service.update_page(unique_name, update_data, current_user.id)


@router.delete("/pages/{unique_name}", status_code=204, summary="Delete page")
async def delete_page(
    unique_name: str,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service),
):
    """Soft delete a page (admin only). Returns 204."""
    success = await core_service.delete_page(unique_name)
    if not success:
        raise NotFoundException(detail="Page not found", error_code="PAGE_NOT_FOUND")

    return Response(status_code=204)


# ============================================================================
# APP VERSION ENDPOINTS
# ============================================================================


@router.post(
    "/versions", response_model=AppVersionResponse, status_code=201, summary="Create app version"
)
@invalidate_cache([CacheKeyPatterns.VERSIONS])
async def create_app_version(
    version_data: AppVersionCreate,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service),
):
    """Create a new app version entry (admin only). Invalidates version cache."""
    return await core_service.create_app_version(version_data)


@router.post(
    "/versions/check", response_model=AppVersionCheckResponse, summary="Check for app updates"
)
async def check_for_updates(
    check_data: AppVersionCheckRequest, core_service: CoreService = Depends(get_core_service)
):
    """Check if there's an available update (public endpoint, cached)."""
    try:
        return await check_for_updates_cached(
            core_service,
            app=check_data.app.value,
            platform=check_data.platform.value,
            current_version=check_data.current_version,
            build_number=check_data.build_number,
        )
    except HTTPException:
        raise
    except Exception as exc:
        if is_transient_db_error(exc) or is_statement_timeout(exc):
            error_code = extract_db_error_code(exc) or (
                "STATEMENT_TIMEOUT" if is_statement_timeout(exc) else "TRANSIENT_DB_ERROR"
            )
            logger.error(
                "Version check transient DB failure",
                extra={"endpoint": "check_for_updates", "error_code": error_code},
                exc_info=True,
            )
            raise ServiceUnavailableException(
                detail="Version check is temporarily unavailable. Please retry shortly.",
                headers={"Retry-After": "30"},
                details={"error_code": error_code, "endpoint": "check_for_updates"},
            ) from exc
        logger.error("Error in check_for_updates: %s", exc, exc_info=True)
        raise


@router.get("/versions", response_model=CursorPage[AppVersionResponse], summary="List app versions")
async def get_app_versions(
    app: AppKey | None = Query(None, description="Filter by app identifier"),
    platform: DevicePlatform | None = Query(None, description="Filter by platform"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service),
):
    """Get app versions (admin only)"""
    app_value = app.value if app else None
    platform_value = platform.value if platform else None
    filters = {"app": app_value, "platform": platform_value, "is_active": is_active}
    rows, next_payload, total = await core_service.get_app_versions(
        app=app_value,
        platform=platform_value,
        is_active=is_active,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        rows, limit=page.limit, next_payload=next_payload, total=total, filters=filters
    )


@router.put(
    "/versions/{version_id}", response_model=AppVersionResponse, summary="Update app version"
)
@invalidate_cache([CacheKeyPatterns.VERSIONS])
async def update_app_version(
    version_id: int,
    update_data: AppVersionUpdate,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service),
):
    """Update an app version entry (admin only). Invalidates version cache."""
    return await core_service.update_app_version(version_id, update_data)


# ============================================================================
# FAQ ENDPOINTS
# ============================================================================


@router.post("/faqs", response_model=FAQResponse, status_code=201, summary="Create FAQ")
@invalidate_cache([CacheKeyPatterns.FAQS])
async def create_faq(
    faq_data: FAQCreate,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service),
):
    """Create a new FAQ (admin only). Invalidates FAQ cache."""
    return await core_service.create_faq(faq_data)


@router.get("/faqs", response_model=CursorPage[FAQResponse], summary="List FAQs (admin)")
async def get_faqs_admin(
    category: str | None = Query(None, description="Filter by category/platform"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    page: CursorParams = Depends(),
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service),
):
    """Get FAQs with admin filters (admin only)"""
    filters = {"category": category, "is_active": is_active}
    rows, next_payload, total = await core_service.get_faqs(
        category=category,
        is_active=is_active,
        cursor_payload=page.decoded(filters),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [FAQResponse.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )


@router.get("/faqs/public", response_model=CursorPage[FAQResponse], summary="List FAQs (public)")
async def get_faqs_public(
    category: str | None = Query(None, description="Filter by category/platform"),
    page: CursorParams = Depends(),
    core_service: CoreService = Depends(get_core_service),
):
    """Public FAQs listing (only active FAQs, cached 6hrs)."""
    filters = {"category": category}
    rows, next_payload, total = await get_faqs_public_cached(
        core_service,
        category=category,
        limit=page.limit,
        cursor_payload=page.decoded(filters),
    )
    return build_cursor_page(
        [FAQResponse.model_validate(r) for r in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
        filters=filters,
    )


@router.put("/faqs/{faq_id}", response_model=FAQResponse, summary="Update FAQ")
@invalidate_cache([CacheKeyPatterns.FAQS])
async def update_faq(
    faq_id: int,
    update_data: FAQUpdate,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service),
):
    """Update an FAQ (admin only). Invalidates FAQ cache."""
    return await core_service.update_faq(faq_id, update_data)


@router.delete("/faqs/{faq_id}", status_code=204, summary="Delete FAQ")
@invalidate_cache([CacheKeyPatterns.FAQS])
async def delete_faq(
    faq_id: int,
    current_user: User = Depends(get_current_admin),
    core_service: CoreService = Depends(get_core_service),
):
    """Soft delete an FAQ (admin only). Invalidates FAQ cache. Returns 204."""
    success = await core_service.delete_faq(faq_id)
    if not success:
        raise NotFoundException(detail="FAQ not found", error_code="FAQ_NOT_FOUND")
    return Response(status_code=204)
