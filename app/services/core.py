from __future__ import annotations

import re

from sqlalchemy import ColumnElement, and_, desc, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.core.logging import get_logger
from app.core.utils import utc_now
from app.models.core import FAQ, AppVersion, BugReport, Page
from app.models.enums import BugSeverity, BugStatus, BugType, UserRole
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
from app.schemas.pagination import (
    keyset_filter,
    keyset_payload,
    keyset_sort_value,
    offset_payload,
    read_offset,
)

logger = get_logger(__name__)


def _version_key(version: str) -> tuple[int, ...]:
    """Numeric parts of a dotted version, without trailing zeros.

    "1.10.0" sorts above "1.9.0", and "1.0.0" equals "1.0".
    """
    # ponytail: pre-release tags ("2.0.0-beta") compare as their digits. Use packaging.version when pre-releases ship.
    parts = [int(part) for part in re.findall(r"\d+", version)]
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


class CoreService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # Bug Report Methods
    async def create_bug_report(
        self, bug_data: BugReportCreate, user_id: int | None = None
    ) -> BugReportResponse:
        """Create a new bug report"""
        bug_report = BugReport(user_id=user_id, **bug_data.model_dump())

        self.db.add(bug_report)
        await self.db.commit()
        await self.db.refresh(bug_report)

        return BugReportResponse.model_validate(bug_report)

    async def get_bug_reports(
        self,
        user_id: int | None = None,
        status: BugStatus | None = None,
        bug_type: BugType | None = None,
        severity: BugSeverity | None = None,
        cursor_payload: dict | None = None,
        limit: int = 20,
        with_total: bool = False,
    ) -> tuple[list[BugReport], dict | None, int | None]:
        """Get bug reports with optional filtering (keyset pagination)."""
        if cursor_payload is None:
            cursor_payload = {}

        stmt = select(BugReport).options(
            selectinload(BugReport.user),
            selectinload(BugReport.assignee),
        )

        if user_id:
            stmt = stmt.where(BugReport.user_id == user_id)

        if status:
            stmt = stmt.where(BugReport.status == status)

        if bug_type:
            stmt = stmt.where(BugReport.bug_type == bug_type)

        if severity:
            stmt = stmt.where(BugReport.severity == severity)

        count_total: int | None = None
        if with_total:
            count_total = (
                await self.db.execute(select(func.count()).select_from(stmt.subquery()))
            ).scalar_one()

        predicate = keyset_filter(
            BugReport.created_at, BugReport.id, cursor_payload, descending=True
        )
        if predicate is not None:
            stmt = stmt.where(predicate)

        stmt = stmt.order_by(BugReport.created_at.desc(), BugReport.id.desc()).limit(limit + 1)
        rows = list((await self.db.execute(stmt)).scalars().all())

        next_payload: dict | None = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_payload = keyset_payload(keyset_sort_value(rows[-1].created_at), rows[-1].id)

        return rows, next_payload, count_total

    async def get_bug_report_by_id(self, bug_id: int) -> BugReportResponse:
        """Get a specific bug report by ID"""
        query = (
            select(BugReport)
            .options(selectinload(BugReport.user), selectinload(BugReport.assignee))
            .where(BugReport.id == bug_id)
        )

        result = await self.db.execute(query)
        bug_report = result.scalar_one_or_none()

        if not bug_report:
            raise NotFoundException(f"Bug report with ID {bug_id} not found")

        return BugReportResponse.model_validate(bug_report)

    async def _require_assignee(self, user_id: int) -> None:
        """A bug can be assigned only to an existing admin or agent (422 otherwise)."""
        role = (
            await self.db.execute(select(User.role).where(User.id == user_id))
        ).scalar_one_or_none()
        if role not in (UserRole.admin, UserRole.agent):
            raise ValidationException(
                "assigned_to must be an existing admin or agent user", error_code="INVALID_ASSIGNEE"
            )

    async def update_bug_report(
        self, bug_id: int, update_data: BugReportUpdate, updated_by: int | None = None
    ) -> BugReportResponse:
        """Update a bug report"""
        # Get the bug report
        bug_report = await self.get_bug_report_by_id(bug_id)

        # Prepare update data
        update_dict = update_data.model_dump(exclude_unset=True)

        assignee_id = update_dict.get("assigned_to")
        if assignee_id is not None:
            await self._require_assignee(assignee_id)

        # If status is being changed to resolved, set resolved_at
        if (
            update_dict.get("status") == BugStatus.resolved
            and bug_report.status != BugStatus.resolved
        ):
            update_dict["resolved_at"] = utc_now()

        # Update the bug report
        query = update(BugReport).where(BugReport.id == bug_id).values(**update_dict)

        await self.db.execute(query)
        await self.db.commit()

        # Return updated bug report
        return await self.get_bug_report_by_id(bug_id)

    # Page Methods
    async def create_page(
        self, page_data: PageCreate, created_by: int | None = None
    ) -> PageResponse:
        """Create a new page"""
        # unique_name is unique across all rows, including soft-deleted (inactive) pages.
        taken = await self.db.execute(
            select(Page.id).where(Page.unique_name == page_data.unique_name)
        )
        if taken.scalar_one_or_none() is not None:
            raise ConflictException(
                f"Page with unique_name '{page_data.unique_name}' already exists",
                error_code="PAGE_EXISTS",
            )

        page = Page(created_by=created_by, **page_data.model_dump())

        self.db.add(page)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ConflictException(
                f"Page with unique_name '{page_data.unique_name}' already exists",
                error_code="PAGE_EXISTS",
            ) from None
        await self.db.refresh(page)

        return PageResponse.model_validate(page)

    async def get_page_by_unique_name(
        self, unique_name: str, *, include_inactive: bool = False
    ) -> PageResponse | None:
        """Get a page by its unique name. Pure read; does NOT modify view_count.

        Inactive (soft-deleted) pages are hidden unless ``include_inactive`` is set (admin reads).
        """
        conditions: list[ColumnElement[bool]] = [Page.unique_name == unique_name]
        if not include_inactive:
            conditions.append(Page.is_active.is_(True))
        query = (
            select(Page)
            .options(selectinload(Page.creator), selectinload(Page.updater))
            .where(and_(*conditions))
        )

        result = await self.db.execute(query)
        page = result.scalar_one_or_none()
        if page:
            return PageResponse.model_validate(page)
        return None

    async def _increment_page_view_count(self, page: Page) -> None:
        """Best-effort view count increment. Raises on DB errors so caller can decide.

        Uses a Core UPDATE (not ORM mutation) so a cosmetic view-count bump does
        not bump the page's updated_at. The Page object is then refreshed.
        """
        await self.db.execute(
            update(Page)
            .where(Page.id == page.id)
            .values(
                view_count=Page.view_count + 1,
                # Preserve updated_at: a view is not a content update.
                updated_at=Page.updated_at,
            )
        )
        await self.db.commit()
        await self.db.refresh(page)

    async def get_page_public(self, unique_name: str) -> PagePublicResponse | None:
        """Get a page for public access (without sensitive data)."""
        query = select(Page).where(
            and_(
                Page.unique_name == unique_name,
                Page.is_active,
                Page.is_draft.is_(False),
                Page.is_private.is_(False),
            )
        )

        result = await self.db.execute(query)
        page = result.scalar_one_or_none()

        if page:
            # Snapshot the response before the best-effort view count increment.
            # If the increment's commit fails (e.g., read-only transaction), the
            # response still reflects the persisted page and is not invalidated
            # by the rolled-back, possibly expired ORM instance.
            response = PagePublicResponse.model_validate(page)
            try:
                await self._increment_page_view_count(page)
                # Re-validate with the refreshed page to include the updated count.
                response = PagePublicResponse.model_validate(page)
            except Exception as view_exc:  # noqa: BLE001
                logger.warning("View count increment failed for %s: %s", unique_name, view_exc)
                try:
                    await self.db.rollback()
                except Exception:  # noqa: BLE001
                    pass

            return response
        return None

    async def get_pages(
        self,
        is_active: bool | None = None,
        is_draft: bool | None = None,
        cursor_payload: dict | None = None,
        limit: int = 20,
        with_total: bool = False,
    ) -> tuple[list[Page], dict | None, int | None]:
        """Get pages with optional filtering (offset-fallback pagination)."""
        if cursor_payload is None:
            cursor_payload = {}

        stmt = select(Page).options(
            selectinload(Page.creator),
            selectinload(Page.updater),
        )

        if is_active is not None:
            stmt = stmt.where(Page.is_active.is_(is_active))

        if is_draft is not None:
            stmt = stmt.where(Page.is_draft.is_(is_draft))

        count_total: int | None = None
        if with_total:
            count_total = (
                await self.db.execute(select(func.count()).select_from(stmt.subquery()))
            ).scalar_one()

        offset = read_offset(cursor_payload)
        stmt = stmt.order_by(desc(Page.updated_at)).offset(offset).limit(limit + 1)
        rows = list((await self.db.execute(stmt)).scalars().all())

        next_pg: dict | None = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_pg = offset_payload(offset + limit)

        return rows, next_pg, count_total

    async def update_page(
        self, unique_name: str, update_data: PageUpdate, updated_by: int | None = None
    ) -> PageResponse:
        """Update a page"""
        # Check if page exists
        existing_page = await self.db.execute(select(Page).where(Page.unique_name == unique_name))
        page = existing_page.scalar_one_or_none()

        if not page:
            raise NotFoundException(f"Page with unique_name '{unique_name}' not found")

        # Prepare update data
        update_dict = update_data.model_dump(exclude_unset=True)

        if updated_by:
            update_dict["updated_by"] = updated_by

        # updated_at onupdate only fires for ORM flushes; this is a Core UPDATE.
        update_dict["updated_at"] = utc_now()

        # Update the page
        query = update(Page).where(Page.unique_name == unique_name).values(**update_dict)

        await self.db.execute(query)
        await self.db.commit()

        # Return the updated page. An update may set is_active=false; the row must still be readable.
        updated_page = await self.get_page_by_unique_name(unique_name, include_inactive=True)
        if updated_page is None:
            raise NotFoundException(f"Page with unique_name '{unique_name}' not found after update")
        return updated_page

    async def delete_page(self, unique_name: str) -> bool:
        """Soft delete a page by setting is_active to False"""
        query = update(Page).where(Page.unique_name == unique_name).values(is_active=False)

        result = await self.db.execute(query)
        await self.db.commit()

        return bool(result.rowcount)  # type: ignore[attr-defined]

    # App Version Methods
    async def create_app_version(self, version_data: AppVersionCreate) -> AppVersionResponse:
        """Create a new app version entry"""
        app_version = AppVersion(**version_data.model_dump(mode="json"))

        self.db.add(app_version)
        await self.db.commit()
        await self.db.refresh(app_version)

        return AppVersionResponse.model_validate(app_version)

    async def check_for_updates(
        self, check_data: AppVersionCheckRequest
    ) -> AppVersionCheckResponse:
        """Check if there's an available update for the given app, platform, and version"""
        query = (
            select(AppVersion)
            .where(
                and_(
                    AppVersion.app == check_data.app.value,
                    AppVersion.platform == check_data.platform.value,
                    AppVersion.is_active,
                )
            )
            .order_by(desc(AppVersion.created_at))
            .limit(1)
        )

        result = await self.db.execute(query)
        latest_version_entry = result.scalar_one_or_none()

        if not latest_version_entry:
            return AppVersionCheckResponse(update_available=False)

        current_version = check_data.current_version
        latest_version = latest_version_entry.version

        # Compare numeric parts, so "1.10.0" is newer than "1.9.0". A client ahead of the latest is not offered an update.
        update_available = _version_key(latest_version) > _version_key(current_version)

        # Same version name: a newer build of the latest release is an update.
        latest_build = latest_version_entry.build_number
        if (
            not update_available
            and check_data.build_number is not None
            and latest_build is not None
            and _version_key(latest_version) == _version_key(current_version)
            and latest_build > check_data.build_number
        ):
            update_available = True

        min_supported = latest_version_entry.min_supported_version
        is_below_min = False
        if min_supported and _version_key(current_version) < _version_key(min_supported):
            is_below_min = True
            update_available = True

        return AppVersionCheckResponse(
            update_available=update_available,
            is_mandatory=latest_version_entry.is_mandatory or is_below_min,
            latest_version=latest_version,
            download_url=latest_version_entry.download_url,
            release_notes=str(latest_version_entry.release_notes)
            if latest_version_entry.release_notes is not None
            else None,
            min_supported_version=min_supported,
        )

    async def get_app_versions(
        self,
        app: str | None = None,
        platform: str | None = None,
        is_active: bool | None = None,
        cursor_payload: dict | None = None,
        limit: int = 10,
        with_total: bool = False,
    ) -> tuple[list[AppVersionResponse], dict | None, int | None]:
        """Get app versions with optional filtering"""
        if cursor_payload is None:
            cursor_payload = {}
        offset = read_offset(cursor_payload)

        query = select(AppVersion)

        if app:
            query = query.where(AppVersion.app == app)

        if platform:
            query = query.where(AppVersion.platform == platform)

        if is_active is not None:
            query = query.where(AppVersion.is_active.is_(is_active))

        total: int | None = None
        if with_total:
            total = (
                await self.db.execute(select(func.count()).select_from(query.subquery()))
            ).scalar_one()

        rows = (
            (
                await self.db.execute(
                    query.order_by(desc(AppVersion.created_at)).offset(offset).limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )

        has_more = len(rows) > limit
        rows = rows[:limit]
        next_payload = offset_payload(offset + limit) if has_more else None

        versions = [AppVersionResponse.model_validate(version) for version in rows]
        return versions, next_payload, total

    async def update_app_version(
        self, version_id: int, update_data: AppVersionUpdate
    ) -> AppVersionResponse:
        """Update an app version entry"""
        existing_version = await self.db.execute(
            select(AppVersion).where(AppVersion.id == version_id)
        )
        app_version = existing_version.scalar_one_or_none()

        if not app_version:
            raise NotFoundException(f"App version with ID {version_id} not found")

        update_dict = update_data.model_dump(mode="json", exclude_unset=True)

        query = update(AppVersion).where(AppVersion.id == version_id).values(**update_dict)

        await self.db.execute(query)
        await self.db.commit()

        result = await self.db.execute(select(AppVersion).where(AppVersion.id == version_id))
        updated_version = result.scalar_one()

        return AppVersionResponse.model_validate(updated_version)

    # FAQ Methods
    async def create_faq(self, faq_data: FAQCreate) -> FAQResponse:
        """Create a new FAQ entry"""
        faq = FAQ(**faq_data.model_dump())
        self.db.add(faq)
        await self.db.commit()
        await self.db.refresh(faq)
        return FAQResponse.model_validate(faq)

    async def get_faqs(
        self,
        category: str | None = None,
        is_active: bool | None = True,
        cursor_payload: dict | None = None,
        limit: int = 50,
        with_total: bool = False,
    ) -> tuple[list[FAQ], dict | None, int | None]:
        """Get FAQs with optional filtering (offset-fallback pagination)."""
        if cursor_payload is None:
            cursor_payload = {}

        stmt = select(FAQ)

        if category:
            stmt = stmt.where(FAQ.category == category)

        if is_active is not None:
            stmt = stmt.where(FAQ.is_active.is_(is_active))

        count_total: int | None = None
        if with_total:
            count_total = (
                await self.db.execute(select(func.count()).select_from(stmt.subquery()))
            ).scalar_one()

        offset = read_offset(cursor_payload)
        stmt = (
            stmt.order_by(FAQ.display_order.asc(), desc(FAQ.created_at))
            .offset(offset)
            .limit(limit + 1)
        )
        rows = list((await self.db.execute(stmt)).scalars().all())

        next_pg: dict | None = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_pg = offset_payload(offset + limit)

        return rows, next_pg, count_total

    async def get_faq_by_id(self, faq_id: int) -> FAQResponse:
        query = select(FAQ).where(FAQ.id == faq_id)
        result = await self.db.execute(query)
        faq = result.scalar_one_or_none()
        if not faq:
            raise NotFoundException(f"FAQ with ID {faq_id} not found", error_code="FAQ_NOT_FOUND")
        return FAQResponse.model_validate(faq)

    async def update_faq(self, faq_id: int, update_data: FAQUpdate) -> FAQResponse:
        # Ensure exists
        _ = await self.get_faq_by_id(faq_id)
        update_dict = update_data.model_dump(exclude_unset=True)
        query = update(FAQ).where(FAQ.id == faq_id).values(**update_dict)
        await self.db.execute(query)
        await self.db.commit()
        # Return updated
        result = await self.db.execute(select(FAQ).where(FAQ.id == faq_id))
        updated = result.scalar_one()
        return FAQResponse.model_validate(updated)

    async def delete_faq(self, faq_id: int) -> bool:
        """Soft delete an FAQ by setting is_active to False"""
        # Ensure exists
        _ = await self.get_faq_by_id(faq_id)
        query = update(FAQ).where(FAQ.id == faq_id).values(is_active=False)
        result = await self.db.execute(query)
        await self.db.commit()
        return bool(result.rowcount)  # type: ignore[attr-defined]
