
from sqlalchemy import and_, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundException, ValidationException
from app.core.utils import utc_now
from app.models.core import FAQ, AppVersion, BugReport, Page
from app.models.enums import BugStatus, BugType
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


class CoreService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # Bug Report Methods
    async def create_bug_report(self, bug_data: BugReportCreate, user_id: int | None = None) -> BugReportResponse:
        """Create a new bug report"""
        bug_report = BugReport(
            user_id=user_id,
            **bug_data.model_dump()
        )

        self.db.add(bug_report)
        await self.db.commit()
        await self.db.refresh(bug_report)

        return BugReportResponse.model_validate(bug_report)

    async def get_bug_reports(
        self,
        user_id: int | None = None,
        status: BugStatus | None = None,
        bug_type: BugType | None = None,
        limit: int = 20,
        offset: int = 0
    ) -> list[BugReportResponse]:
        """Get bug reports with optional filtering"""
        query = select(BugReport).options(
            selectinload(BugReport.user),
            selectinload(BugReport.assignee)
        )

        if user_id:
            query = query.where(BugReport.user_id == user_id)

        if status:
            query = query.where(BugReport.status == status)

        if bug_type:
            query = query.where(BugReport.bug_type == bug_type)

        query = query.order_by(desc(BugReport.created_at)).limit(limit).offset(offset)

        result = await self.db.execute(query)
        bug_reports = result.scalars().all()

        return [BugReportResponse.model_validate(bug) for bug in bug_reports]

    async def get_bug_report_by_id(self, bug_id: int) -> BugReportResponse:
        """Get a specific bug report by ID"""
        query = select(BugReport).options(
            selectinload(BugReport.user),
            selectinload(BugReport.assignee)
        ).where(BugReport.id == bug_id)

        result = await self.db.execute(query)
        bug_report = result.scalar_one_or_none()

        if not bug_report:
            raise NotFoundException(f"Bug report with ID {bug_id} not found")

        return BugReportResponse.model_validate(bug_report)

    async def update_bug_report(
        self,
        bug_id: int,
        update_data: BugReportUpdate,
        updated_by: int | None = None
    ) -> BugReportResponse:
        """Update a bug report"""
        # Get the bug report
        bug_report = await self.get_bug_report_by_id(bug_id)

        # Prepare update data
        update_dict = update_data.model_dump(exclude_unset=True)

        # If status is being changed to resolved, set resolved_at
        if update_dict.get('status') == BugStatus.resolved and bug_report.status != BugStatus.resolved:
            update_dict['resolved_at'] = utc_now()

        # Update the bug report
        query = (
            update(BugReport)
            .where(BugReport.id == bug_id)
            .values(**update_dict)
        )

        await self.db.execute(query)
        await self.db.commit()

        # Return updated bug report
        return await self.get_bug_report_by_id(bug_id)

    # Page Methods
    async def create_page(self, page_data: PageCreate, created_by: int | None = None) -> PageResponse:
        """Create a new page"""
        # Check if unique_name already exists
        existing_page = await self.get_page_by_unique_name(page_data.unique_name)
        if existing_page:
            raise ValidationException(f"Page with unique_name '{page_data.unique_name}' already exists")

        page = Page(
            created_by=created_by,
            **page_data.model_dump()
        )

        self.db.add(page)
        await self.db.commit()
        await self.db.refresh(page)

        return PageResponse.model_validate(page)

    async def get_page_by_unique_name(self, unique_name: str) -> PageResponse | None:
        """Get a page by its unique name"""
        query = select(Page).options(
            selectinload(Page.creator),
            selectinload(Page.updater)
        ).where(
            and_(Page.unique_name == unique_name, Page.is_active)
        )

        result = await self.db.execute(query)
        page = result.scalar_one_or_none()

        if page:
            # Increment view count
            page.view_count += 1
            await self.db.commit()
            await self.db.refresh(page)

            return PageResponse.model_validate(page)
        return None

    async def get_page_public(self, unique_name: str) -> PagePublicResponse | None:
        """Get a page for public access (without sensitive data)"""
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
            # Increment view count
            page.view_count += 1
            await self.db.commit()
            await self.db.refresh(page)

            return PagePublicResponse.model_validate(page)
        return None

    async def get_pages(
        self,
        is_active: bool | None = None,
        is_draft: bool | None = None,
        limit: int = 20,
        offset: int = 0
    ) -> list[PageResponse]:
        """Get pages with optional filtering"""
        query = select(Page).options(
            selectinload(Page.creator),
            selectinload(Page.updater)
        )

        if is_active is not None:
            query = query.where(Page.is_active == is_active)

        if is_draft is not None:
            query = query.where(Page.is_draft == is_draft)

        query = query.order_by(desc(Page.updated_at)).limit(limit).offset(offset)

        result = await self.db.execute(query)
        pages = result.scalars().all()

        return [PageResponse.model_validate(page) for page in pages]

    async def update_page(
        self,
        unique_name: str,
        update_data: PageUpdate,
        updated_by: int | None = None
    ) -> PageResponse:
        """Update a page"""
        # Check if page exists
        existing_page = await self.db.execute(
            select(Page).where(Page.unique_name == unique_name)
        )
        page = existing_page.scalar_one_or_none()

        if not page:
            raise NotFoundException(f"Page with unique_name '{unique_name}' not found")

        # Prepare update data
        update_dict = update_data.model_dump(exclude_unset=True)

        if updated_by:
            update_dict['updated_by'] = updated_by

        # Update the page
        query = (
            update(Page)
            .where(Page.unique_name == unique_name)
            .values(**update_dict)
        )

        await self.db.execute(query)
        await self.db.commit()

        # Return updated page
        updated_page = await self.get_page_by_unique_name(unique_name)
        if updated_page is None:
            raise NotFoundException(f"Page with unique_name '{unique_name}' not found after update")
        return updated_page

    async def delete_page(self, unique_name: str) -> bool:
        """Soft delete a page by setting is_active to False"""
        query = (
            update(Page)
            .where(Page.unique_name == unique_name)
            .values(is_active=False)
        )

        result = await self.db.execute(query)
        await self.db.commit()

        return bool(result.rowcount)  # type: ignore[attr-defined]

    # App Version Methods
    async def create_app_version(self, version_data: AppVersionCreate) -> AppVersionResponse:
        """Create a new app version entry"""
        app_version = AppVersion(**version_data.model_dump())

        self.db.add(app_version)
        await self.db.commit()
        await self.db.refresh(app_version)

        return AppVersionResponse.model_validate(app_version)

    async def check_for_updates(self, check_data: AppVersionCheckRequest) -> AppVersionCheckResponse:
        """Check if there's an available update for the given app, platform, and version"""
        query = (
            select(AppVersion)
            .where(
                and_(
                    AppVersion.app == check_data.app,
                    AppVersion.platform == check_data.platform,
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

        # Simple version comparison (consider using proper semver comparison in production)
        update_available = latest_version != current_version

        min_supported = latest_version_entry.min_supported_version
        is_below_min = False
        if min_supported and current_version < min_supported:
            is_below_min = True
            update_available = True

        return AppVersionCheckResponse(
            update_available=update_available,
            is_mandatory=latest_version_entry.is_mandatory or is_below_min,
            latest_version=latest_version,
            download_url=latest_version_entry.download_url,
            release_notes=str(latest_version_entry.release_notes) if latest_version_entry.release_notes is not None else None,
            min_supported_version=min_supported,
        )

    async def get_app_versions(
        self,
        app: str | None = None,
        platform: str | None = None,
        is_active: bool | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[AppVersionResponse]:
        """Get app versions with optional filtering"""
        query = select(AppVersion)

        if app:
            query = query.where(AppVersion.app == app)

        if platform:
            query = query.where(AppVersion.platform == platform)

        if is_active is not None:
            query = query.where(AppVersion.is_active == is_active)

        query = query.order_by(desc(AppVersion.created_at)).limit(limit).offset(offset)

        result = await self.db.execute(query)
        versions = result.scalars().all()

        return [AppVersionResponse.model_validate(version) for version in versions]

    async def update_app_version(
        self,
        version_id: int,
        update_data: AppVersionUpdate
    ) -> AppVersionResponse:
        """Update an app version entry"""
        existing_version = await self.db.execute(
            select(AppVersion).where(AppVersion.id == version_id)
        )
        app_version = existing_version.scalar_one_or_none()

        if not app_version:
            raise NotFoundException(f"App version with ID {version_id} not found")

        update_dict = update_data.model_dump(exclude_unset=True)

        query = (
            update(AppVersion)
            .where(AppVersion.id == version_id)
            .values(**update_dict)
        )

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
        limit: int = 50,
        offset: int = 0
    ) -> list[FAQResponse]:
        """Get FAQs with optional filtering by category and active status"""
        query = select(FAQ)

        if category:
            query = query.where(FAQ.category == category)

        if is_active is not None:
            query = query.where(FAQ.is_active == is_active)

        # Order by display_order ascending, then most recent
        query = query.order_by(FAQ.display_order.asc(), desc(FAQ.created_at)).limit(limit).offset(offset)

        result = await self.db.execute(query)
        faqs = result.scalars().all()
        return [FAQResponse.model_validate(faq) for faq in faqs]

    async def get_faq_by_id(self, faq_id: int) -> FAQResponse:
        query = select(FAQ).where(FAQ.id == faq_id)
        result = await self.db.execute(query)
        faq = result.scalar_one_or_none()
        if not faq:
            raise NotFoundException(f"FAQ with ID {faq_id} not found")
        return FAQResponse.model_validate(faq)

    async def update_faq(self, faq_id: int, update_data: FAQUpdate) -> FAQResponse:
        # Ensure exists
        _ = await self.get_faq_by_id(faq_id)
        update_dict = update_data.model_dump(exclude_unset=True)
        query = (
            update(FAQ)
            .where(FAQ.id == faq_id)
            .values(**update_dict)
        )
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
        query = (
            update(FAQ)
            .where(FAQ.id == faq_id)
            .values(is_active=False)
        )
        result = await self.db.execute(query)
        await self.db.commit()
        return bool(result.rowcount)  # type: ignore[attr-defined]
