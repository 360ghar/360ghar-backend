"""
Tests for core endpoints (health, config, etc.).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.enums import BugSeverity, BugStatus, BugType
from app.schemas.core import BugReportResponse


def create_mock_bug_report_response() -> BugReportResponse:
    """Build a valid BugReportResponse payload for endpoint tests."""
    return BugReportResponse(
        id=1,
        user_id=1,
        source="web",
        bug_type=BugType.ui_bug,
        severity=BugSeverity.medium,
        status=BugStatus.open,
        title="UI issue",
        description="Buttons overlap on mobile layout.",
        steps_to_reproduce="Open page on iPhone width.",
        expected_behavior="Buttons should stack correctly.",
        actual_behavior="Buttons overlap each other.",
        device_info={"os": "iOS"},
        app_version="1.0.0",
        media_urls=["https://cdn.example.com/uploads/bug.png"],
        tags=["ui", "mobile"],
        assigned_to=None,
        resolution=None,
        resolved_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=None,
    )


class TestHealthEndpoint:
    """Tests for GET /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        """Test health check endpoint."""
        response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data or data.get("ok") is True


class TestRootEndpoint:
    """Tests for GET / endpoint."""

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client: AsyncClient):
        """Test root endpoint."""
        response = await client.get("/")

        assert response.status_code == 200


class TestDocsEndpoint:
    """Tests for documentation endpoints."""

    @pytest.mark.asyncio
    async def test_swagger_docs(self, client: AsyncClient):
        """Test Swagger UI endpoint."""
        response = await client.get("/api/v1/docs")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_redoc(self, client: AsyncClient):
        """Test ReDoc endpoint."""
        response = await client.get("/api/v1/redoc")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_openapi_json(self, client: AsyncClient):
        """Test OpenAPI JSON endpoint."""
        response = await client.get("/api/v1/openapi.json")

        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data


class TestFAQEndpoints:
    """Tests for FAQ endpoints."""

    @pytest.mark.asyncio
    async def test_get_faqs_public(self, client: AsyncClient):
        """Test getting public FAQs."""
        with patch(
            "app.api.api_v1.endpoints.core.get_faqs_public_cached",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = ([], None, None)

            response = await client.get("/api/v1/faqs/public")

            assert response.status_code == 200


class TestVersionEndpoints:
    """Tests for version check endpoints."""

    @pytest.mark.asyncio
    async def test_check_for_updates(self, client: AsyncClient):
        """Test checking for app updates."""
        with patch(
            "app.api.api_v1.endpoints.core.check_for_updates_cached",
            new_callable=AsyncMock,
        ) as mock_check:
            mock_check.return_value = {
                "update_available": False,
                "latest_version": "1.0.0",
                "force_update": False,
            }

            response = await client.post(
                "/api/v1/versions/check",
                json={
                    "app": "360ghar",
                    "platform": "android",
                    "current_version": "1.0.0",
                },
            )

            assert response.status_code == 200


class TestBugEndpoints:
    """Tests for bug report endpoints."""

    @pytest.mark.asyncio
    async def test_create_bug_report_with_media_uses_form_fields(
        self,
        authenticated_client: AsyncClient,
    ):
        """Multipart fields should be parsed from form body and forwarded as typed schema."""
        with patch(
            "app.api.api_v1.endpoints.core.storage_service.upload_generic",
            new_callable=AsyncMock,
        ) as mock_upload, patch(
            "app.services.core.CoreService.create_bug_report",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_upload.return_value = {"public_url": "https://cdn.example.com/uploads/bug.png"}
            mock_create.return_value = create_mock_bug_report_response()

            response = await authenticated_client.post(
                "/api/v1/bugs/with-media/",
                data={
                    "source": "web",
                    "bug_type": "ui_bug",
                    "severity": "medium",
                    "title": "UI issue",
                    "description": "Buttons overlap on mobile layout.",
                    "steps_to_reproduce": "Open page on iPhone width.",
                    "expected_behavior": "Buttons should stack correctly.",
                    "actual_behavior": "Buttons overlap each other.",
                    "device_info": "{\"os\":\"iOS\"}",
                    "app_version": "1.0.0",
                    "tags": "[\"ui\",\"mobile\"]",
                },
                files=[
                    ("files", ("bug.png", b"fake-image-content", "image/png")),
                ],
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["bug_type"] == "ui_bug"
            assert payload["media_urls"] == ["https://cdn.example.com/uploads/bug.png"]

            create_args = mock_create.await_args.args
            bug_data = create_args[0]
            assert bug_data.source == "web"
            assert bug_data.bug_type == BugType.ui_bug
            assert bug_data.device_info == {"os": "iOS"}
            assert bug_data.tags == ["ui", "mobile"]
            assert bug_data.media_urls == ["https://cdn.example.com/uploads/bug.png"]
