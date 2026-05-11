"""
Unit tests for the flatmates admin moderation endpoints.

Tests cover:
- Non-admin users receive 403 on all moderation endpoints
- moderate_listing with approve / reject / request_edit actions
- moderate_report with dismiss / warn_user / suspend_user / escalate actions
- get_pending_listings and get_pending_reports pagination
- prescreen_listing requires admin
- Database and service calls are mocked throughout
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.api_v1.endpoints.flatmates_admin import (
    _is_admin_user,
    _serialize_flatmate_listing,
    _serialize_report,
    get_pending_listings,
    get_pending_reports,
    moderate_listing,
    moderate_report,
    prescreen_listing,
)
from app.schemas.flatmates import ListingModerationAction, ReportModerationAction

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user_schema(
    user_id: int = 1,
    role: str = "user",
    full_name: str = "Test User",
    is_admin: bool = False,
) -> SimpleNamespace:
    """Build a lightweight user schema stand-in for dependency injection."""
    return SimpleNamespace(
        id=user_id,
        role=role,
        is_admin=is_admin,
        full_name=full_name,
        email="test@example.com",
        phone="+919876543210",
        is_active=True,
    )


def _make_admin_user_schema() -> SimpleNamespace:
    return _make_user_schema(user_id=99, role="admin", is_admin=True, full_name="Admin User")


def _make_property(
    prop_id: int = 1,
    title: str = "Test Listing",
    property_type: str = "flatmate",
    purpose: str = "rent",
    owner_id: int = 10,
    listing_preferences: dict | None = None,
) -> SimpleNamespace:
    prefs = listing_preferences or {"moderation_status": "pending_review"}
    return SimpleNamespace(
        id=prop_id,
        title=title,
        description="A nice room",
        property_type=property_type,
        purpose=purpose,
        status="available",
        listing_preferences=prefs,
        monthly_rent=10000.0,
        security_deposit=20000.0,
        maintenance_charges=500.0,
        area_sqft=200.0,
        bedrooms=1,
        bathrooms=1,
        features=["WiFi", "AC"],
        images=[],
        image_urls=[],
        city="Gurugram",
        locality="Sector 43",
        sub_locality=None,
        main_image_url=None,
        owner_id=owner_id,
        owner=SimpleNamespace(
            id=owner_id,
            full_name="Owner",
            email="owner@example.com",
            phone="+919999999999",
            profile_image_url=None,
        ),
        is_available=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _make_report(
    report_id: int = 1,
    reporter_user_id: int = 10,
    reported_user_id: int = 20,
    reason: str = "spam",
    status: str = "open",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=report_id,
        reporter_user_id=reporter_user_id,
        reported_user_id=reported_user_id,
        conversation_id=None,
        property_id=None,
        reason=reason,
        status=status,
        notes=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _mock_db() -> AsyncMock:
    """Build a mock AsyncSession for unit tests."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _scalar_result(value):
    """Build a MagicMock with scalar_one_or_none returning value.

    Used to mock the result of `await db.execute(stmt)` which
    returns a sync Result object.
    """
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ===========================================================================
# Helper function tests
# ===========================================================================


class TestIsAdminUser:
    """Tests for _is_admin_user helper."""

    def test_admin_role_returns_true(self):
        user = _make_user_schema(role="admin")
        assert _is_admin_user(user) is True

    def test_regular_user_returns_false(self):
        user = _make_user_schema(role="user")
        assert _is_admin_user(user) is False

    def test_agent_returns_false(self):
        user = _make_user_schema(role="agent")
        assert _is_admin_user(user) is False


class TestSerializeFlatmateListing:
    """Tests for _serialize_flatmate_listing helper."""

    def test_serializes_core_fields(self):
        prop = _make_property(prop_id=42, title="Nice Room")
        result = _serialize_flatmate_listing(prop)

        assert result["id"] == 42
        assert result["title"] == "Nice Room"
        assert result["property_type"] == "flatmate"
        assert result["moderation_status"] == "pending_review"
        assert result["city"] == "Gurugram"
        assert result["owner"]["full_name"] == "Owner"

    def test_handles_missing_preferences(self):
        prop = _make_property()
        prop.listing_preferences = None
        result = _serialize_flatmate_listing(prop)
        assert result["moderation_status"] == "pending_review"

    def test_features_list_serialized(self):
        prop = _make_property()
        result = _serialize_flatmate_listing(prop)
        assert "WiFi" in result["features"]


class TestSerializeReport:
    """Tests for _serialize_report helper."""

    def test_serializes_report_fields(self):
        report = _make_report(report_id=5, reason="fake_profile", status="open")
        result = _serialize_report(report)

        assert result["id"] == 5
        assert result["reason"] == "fake_profile"
        assert result["status"] == "open"

    def test_user_map_populated(self):
        report = _make_report(reporter_user_id=10, reported_user_id=20)
        user_map = {
            10: SimpleNamespace(
                id=10, full_name="Reporter", email="r@x.com", phone="+91", profile_image_url=None
            ),
            20: SimpleNamespace(
                id=20, full_name="Reported", email="d@x.com", phone="+92", profile_image_url=None
            ),
        }
        result = _serialize_report(report, user_map)

        assert result["reporter"]["full_name"] == "Reporter"
        assert result["reported_user"]["full_name"] == "Reported"


# ===========================================================================
# Authorization tests
# ===========================================================================


class TestGetPendingListingsAuth:
    """Non-admin users must receive 403 on get_pending_listings."""

    @pytest.mark.asyncio
    async def test_regular_user_gets_403(self):
        db = _mock_db()
        user = _make_user_schema(role="user")

        with pytest.raises(HTTPException) as exc_info:
            await get_pending_listings(
                status="pending_review",
                limit=50,
                offset=0,
                current_user=user,
                db=db,
            )

        assert exc_info.value.status_code == 403
        assert "Admin" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_agent_gets_403(self):
        db = _mock_db()
        user = _make_user_schema(role="agent")

        with pytest.raises(HTTPException) as exc_info:
            await get_pending_listings(
                status="pending_review",
                limit=50,
                offset=0,
                current_user=user,
                db=db,
            )

        assert exc_info.value.status_code == 403


class TestModerateListingAuth:
    """Non-admin users must receive 403 on moderate_listing."""

    @pytest.mark.asyncio
    async def test_regular_user_gets_403(self):
        db = _mock_db()
        user = _make_user_schema(role="user")
        payload = ListingModerationAction(action="approve", reason="Looks good")

        with pytest.raises(HTTPException) as exc_info:
            await moderate_listing(
                listing_id=1,
                payload=payload,
                current_user=user,
                db=db,
            )

        assert exc_info.value.status_code == 403


class TestGetPendingReportsAuth:
    """Non-admin users must receive 403 on get_pending_reports."""

    @pytest.mark.asyncio
    async def test_regular_user_gets_403(self):
        db = _mock_db()
        user = _make_user_schema(role="user")

        with pytest.raises(HTTPException) as exc_info:
            await get_pending_reports(
                status="open",
                limit=50,
                offset=0,
                current_user=user,
                db=db,
            )

        assert exc_info.value.status_code == 403


class TestModerateReportAuth:
    """Non-admin users must receive 403 on moderate_report."""

    @pytest.mark.asyncio
    async def test_regular_user_gets_403(self):
        db = _mock_db()
        user = _make_user_schema(role="user")
        payload = ReportModerationAction(action="dismiss", notes="No violation")

        with pytest.raises(HTTPException) as exc_info:
            await moderate_report(
                report_id=1,
                payload=payload,
                current_user=user,
                db=db,
            )

        assert exc_info.value.status_code == 403


class TestPrescreenListingAuth:
    """Non-admin users must receive 403 on prescreen_listing."""

    @pytest.mark.asyncio
    async def test_regular_user_gets_403(self):
        db = _mock_db()
        user = _make_user_schema(role="user")

        with pytest.raises(HTTPException) as exc_info:
            await prescreen_listing(
                listing_id=1,
                current_user=user,
                db=db,
            )

        assert exc_info.value.status_code == 403


# ===========================================================================
# Listing moderation logic
# ===========================================================================


class TestModerateListingApprove:
    """Tests for approve action on moderate_listing."""

    @pytest.mark.asyncio
    async def test_approve_sets_listing_live(self):
        db = _mock_db()
        admin = _make_admin_user_schema()
        prop = _make_property(prop_id=1, owner_id=10)

        # db.execute returns awaitable, result has scalar_one_or_none (sync)
        db.execute = AsyncMock(return_value=_scalar_result(prop))

        payload = ListingModerationAction(action="approve", reason="Looks good")

        with patch(
            "app.services.push_notification.notify_listing_approved",
            new=AsyncMock(),
        ):
            result = await moderate_listing(
                listing_id=1,
                payload=payload,
                current_user=admin,
                db=db,
            )

        assert result["listing_id"] == 1
        assert result["action"] == "approve"
        assert result["status"] == "live"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_approve_emits_sse_event(self):
        """Approve action emits SSE listing_status_changed event to the listing owner."""
        db = _mock_db()
        admin = _make_admin_user_schema()
        prop = _make_property(prop_id=1, owner_id=10)

        db.execute = AsyncMock(return_value=_scalar_result(prop))

        payload = ListingModerationAction(action="approve", reason="Looks good")

        mock_sse_bus = AsyncMock()
        with (
            patch("app.services.push_notification.notify_listing_approved", new=AsyncMock()),
            patch("app.core.sse.sse_bus", mock_sse_bus),
        ):
            result = await moderate_listing(
                listing_id=1,
                payload=payload,
                current_user=admin,
                db=db,
            )

        mock_sse_bus.emit.assert_awaited_once_with(
            10,
            {
                "type": "listing_status_changed",
                "listing_id": 1,
                "status": "live",
                "reason": "Looks good",
            },
        )
        assert result["status"] == "live"


class TestModerateListingReject:
    """Tests for reject action on moderate_listing."""

    @pytest.mark.asyncio
    async def test_reject_sets_listing_rejected(self):
        db = _mock_db()
        admin = _make_admin_user_schema()
        prop = _make_property(prop_id=2, owner_id=10)

        db.execute = AsyncMock(return_value=_scalar_result(prop))

        payload = ListingModerationAction(action="reject", reason="Incomplete info")

        with patch(
            "app.services.push_notification._dispatch",
            new=AsyncMock(),
        ):
            result = await moderate_listing(
                listing_id=2,
                payload=payload,
                current_user=admin,
                db=db,
            )

        assert result["listing_id"] == 2
        assert result["action"] == "reject"
        assert result["status"] == "rejected"
        assert result["reason"] == "Incomplete info"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reject_emits_sse_event(self):
        """Reject action emits SSE listing_status_changed event to the listing owner."""
        db = _mock_db()
        admin = _make_admin_user_schema()
        prop = _make_property(prop_id=2, owner_id=10)

        db.execute = AsyncMock(return_value=_scalar_result(prop))

        payload = ListingModerationAction(action="reject", reason="Incomplete info")

        mock_sse_bus = AsyncMock()
        with (
            patch("app.services.push_notification._dispatch", new=AsyncMock()),
            patch("app.core.sse.sse_bus", mock_sse_bus),
        ):
            result = await moderate_listing(
                listing_id=2,
                payload=payload,
                current_user=admin,
                db=db,
            )

        mock_sse_bus.emit.assert_awaited_once_with(
            10,
            {
                "type": "listing_status_changed",
                "listing_id": 2,
                "status": "rejected",
                "reason": "Incomplete info",
            },
        )
        assert result["status"] == "rejected"


class TestModerateListingRequestEdit:
    """Tests for request_edit action on moderate_listing."""

    @pytest.mark.asyncio
    async def test_request_edit_sets_pending_review(self):
        db = _mock_db()
        admin = _make_admin_user_schema()
        prop = _make_property(prop_id=3, owner_id=10)

        db.execute = AsyncMock(return_value=_scalar_result(prop))

        payload = ListingModerationAction(action="request_edit", reason="Need better photos")

        result = await moderate_listing(
            listing_id=3,
            payload=payload,
            current_user=admin,
            db=db,
        )

        assert result["listing_id"] == 3
        assert result["action"] == "request_edit"
        assert result["status"] == "pending_review"
        db.commit.assert_awaited_once()


class TestModerateListingNotFound:
    """Tests for moderate_listing when listing is not found."""

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        db = _mock_db()
        admin = _make_admin_user_schema()

        db.execute = AsyncMock(return_value=_scalar_result(None))

        payload = ListingModerationAction(action="approve", reason="OK")

        with pytest.raises(HTTPException) as exc_info:
            await moderate_listing(
                listing_id=999,
                payload=payload,
                current_user=admin,
                db=db,
            )

        assert exc_info.value.status_code == 404


class TestModerateListingApprovalBoost:
    """Tests for approval boost on first approval."""

    @pytest.mark.asyncio
    async def test_first_approval_grants_boost(self):
        db = _mock_db()
        admin = _make_admin_user_schema()
        prop = _make_property(
            prop_id=10,
            owner_id=10,
            listing_preferences={"moderation_status": "pending_review"},
        )

        db.execute = AsyncMock(return_value=_scalar_result(prop))

        payload = ListingModerationAction(action="approve")

        with patch(
            "app.services.push_notification.notify_listing_approved",
            new=AsyncMock(),
        ):
            result = await moderate_listing(
                listing_id=10,
                payload=payload,
                current_user=admin,
                db=db,
            )

        assert result["status"] == "live"
        assert "approval_boost_granted_at" in prop.listing_preferences


# ===========================================================================
# Report moderation logic
# ===========================================================================


class TestModerateReportDismiss:
    """Tests for dismiss action on moderate_report."""

    @pytest.mark.asyncio
    async def test_dismiss_sets_status(self):
        db = _mock_db()
        admin = _make_admin_user_schema()
        report = _make_report(report_id=1, status="open")

        db.execute = AsyncMock(return_value=_scalar_result(report))

        payload = ReportModerationAction(action="dismiss", notes="No violation found")

        with patch(
            "app.services.push_notification._dispatch",
            new=AsyncMock(),
        ):
            result = await moderate_report(
                report_id=1,
                payload=payload,
                current_user=admin,
                db=db,
            )

        assert result["report_id"] == 1
        assert result["action"] == "dismiss"
        assert result["status"] == "dismissed"
        assert result["notes"] == "No violation found"
        db.commit.assert_awaited_once()


class TestModerateReportWarnUser:
    """Tests for warn_user action on moderate_report."""

    @pytest.mark.asyncio
    async def test_warn_user_sets_status_actioned(self):
        db = _mock_db()
        admin = _make_admin_user_schema()
        report = _make_report(report_id=2, status="open")

        db.execute = AsyncMock(return_value=_scalar_result(report))

        payload = ReportModerationAction(action="warn_user", notes="First warning issued")

        with patch(
            "app.services.push_notification._dispatch",
            new=AsyncMock(),
        ):
            result = await moderate_report(
                report_id=2,
                payload=payload,
                current_user=admin,
                db=db,
            )

        assert result["report_id"] == 2
        assert result["action"] == "warn_user"
        assert result["status"] == "actioned"
        db.commit.assert_awaited_once()


class TestModerateReportSuspendUser:
    """Tests for suspend_user action on moderate_report."""

    @pytest.mark.asyncio
    async def test_suspend_user_deactivates_account(self):
        db = _mock_db()
        admin = _make_admin_user_schema()
        report = _make_report(
            report_id=3,
            reported_user_id=20,
            status="open",
        )
        reported_user = SimpleNamespace(id=20, is_active=True)

        # First execute returns report, second returns user
        db.execute = AsyncMock(
            side_effect=[_scalar_result(report), _scalar_result(reported_user)]
        )

        payload = ReportModerationAction(action="suspend_user", notes="Severe violation")

        with patch(
            "app.services.push_notification._dispatch",
            new=AsyncMock(),
        ):
            result = await moderate_report(
                report_id=3,
                payload=payload,
                current_user=admin,
                db=db,
            )

        assert result["status"] == "actioned"
        assert reported_user.is_active is False
        db.commit.assert_awaited_once()


class TestModerateReportEscalate:
    """Tests for escalate action on moderate_report."""

    @pytest.mark.asyncio
    async def test_escalate_sets_status_reviewed(self):
        db = _mock_db()
        admin = _make_admin_user_schema()
        report = _make_report(report_id=4, status="open")

        db.execute = AsyncMock(return_value=_scalar_result(report))

        payload = ReportModerationAction(action="escalate", notes="Needs legal review")

        result = await moderate_report(
            report_id=4,
            payload=payload,
            current_user=admin,
            db=db,
        )

        assert result["report_id"] == 4
        assert result["action"] == "escalate"
        assert result["status"] == "reviewed"
        db.commit.assert_awaited_once()


class TestModerateReportNotFound:
    """Tests for moderate_report when report is not found."""

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        db = _mock_db()
        admin = _make_admin_user_schema()

        db.execute = AsyncMock(return_value=_scalar_result(None))

        payload = ReportModerationAction(action="dismiss", notes="N/A")

        with pytest.raises(HTTPException) as exc_info:
            await moderate_report(
                report_id=999,
                payload=payload,
                current_user=admin,
                db=db,
            )

        assert exc_info.value.status_code == 404


# ===========================================================================
# Pagination tests
# ===========================================================================


class TestGetPendingListingsPagination:
    """Tests for get_pending_listings with admin user and pagination."""

    @pytest.mark.asyncio
    async def test_returns_listings_with_pagination(self):
        db = _mock_db()
        admin = _make_admin_user_schema()

        prop1 = _make_property(prop_id=1)
        prop2 = _make_property(prop_id=2)

        # First db.execute -> listing query (returns scalars().all())
        # Second db.execute -> count query (returns scalar())
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [prop1, prop2]

        mock_listings_result = MagicMock()
        mock_listings_result.scalars.return_value = mock_scalars
        mock_listings_result.scalar.return_value = 2

        db.execute = AsyncMock(side_effect=[mock_listings_result, mock_listings_result])

        with patch(
            "app.api.api_v1.endpoints.flatmates_admin.pause_expired_flatmate_listings",
            new=AsyncMock(),
        ):
            result = await get_pending_listings(
                status="pending_review",
                limit=50,
                offset=0,
                current_user=admin,
                db=db,
            )

        assert "listings" in result
        assert result["total"] == 2
        assert result["limit"] == 50
        assert result["offset"] == 0


class TestGetPendingReportsPagination:
    """Tests for get_pending_reports with admin user and pagination."""

    @pytest.mark.asyncio
    async def test_returns_reports_with_pagination(self):
        db = _mock_db()
        admin = _make_admin_user_schema()

        report1 = _make_report(report_id=1)
        report2 = _make_report(report_id=2)

        # First execute -> reports, second -> user lookup, third -> count
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [report1, report2]

        mock_reports_result = MagicMock()
        mock_reports_result.scalars.return_value = mock_scalars

        mock_users_result = MagicMock()
        mock_users_result.scalars.return_value.all.return_value = []

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 2

        db.execute = AsyncMock(
            side_effect=[mock_reports_result, mock_users_result, mock_count_result]
        )

        result = await get_pending_reports(
            status="open",
            limit=50,
            offset=0,
            current_user=admin,
            db=db,
        )

        assert "reports" in result
        assert result["total"] == 2
        assert result["limit"] == 50
        assert result["offset"] == 0

    @pytest.mark.asyncio
    async def test_empty_reports(self):
        db = _mock_db()
        admin = _make_admin_user_schema()

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []

        mock_reports_result = MagicMock()
        mock_reports_result.scalars.return_value = mock_scalars

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        db.execute = AsyncMock(side_effect=[mock_reports_result, mock_count_result])

        result = await get_pending_reports(
            status="open",
            limit=50,
            offset=0,
            current_user=admin,
            db=db,
        )

        assert result["reports"] == []
        assert result["total"] == 0


# ===========================================================================
# Prescreen listing
# ===========================================================================


class TestPrescreenListing:
    """Tests for prescreen_listing endpoint."""

    @pytest.mark.asyncio
    async def test_admin_can_prescreen(self):
        db = _mock_db()
        admin = _make_admin_user_schema()

        with patch(
            "app.api.api_v1.endpoints.flatmates_admin.prescreen_flatmate_listing",
            new=AsyncMock(return_value={"listing_id": 1, "result": "pass"}),
        ) as mock_prescreen:
            result = await prescreen_listing(
                listing_id=1,
                current_user=admin,
                db=db,
            )

        assert result["listing_id"] == 1
        mock_prescreen.assert_awaited_once_with(db, 1, admin_user_id=admin.id)

    @pytest.mark.asyncio
    async def test_non_admin_gets_403(self):
        db = _mock_db()
        user = _make_user_schema(role="user")

        with pytest.raises(HTTPException) as exc_info:
            await prescreen_listing(
                listing_id=1,
                current_user=user,
                db=db,
            )

        assert exc_info.value.status_code == 403
