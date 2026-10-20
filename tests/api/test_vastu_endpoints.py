"""
Tests for Vastu checker endpoints.

These tests verify the vastu-related API endpoints work correctly.
They mock the service layer to isolate endpoint testing.
"""

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from PIL import Image

from app.core.utils import utc_now_iso
from app.services.ai.vastu import (
    VastuAnalysisResult,
    VastuAnalyzeResponse,
)
from app.services.ai.vastu.schemas import FloorPlanAnalysis


def make_test_image_bytes(fmt: str = "PNG") -> bytes:
    """Build a real decodable image so the endpoint's format-validation passes."""
    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(200, 100, 50)).save(buf, format=fmt)
    return buf.getvalue()


def create_mock_vastu_response(vastu_score: int = 7) -> VastuAnalyzeResponse:
    """Create a mock vastu analysis response."""
    floor_plan_analysis = FloorPlanAnalysis(
        plot_shape="rectangular",
        rooms=[],
        entrance=None,
        kitchen=None,
        toilets=None,
        staircase=None,
        balconies=None,
        open_spaces=None,
        center_area=None,
        compass_visible=False,
    )
    data = VastuAnalysisResult(
        floor_plan_analysis=floor_plan_analysis,
        vastu_score=vastu_score,
        score_explanation="Good overall layout",
        assumptions=["North is at top"],
        room_analysis=[],
        major_defects=[],
        remedies=[],
        improvements=[],
        disclaimer="For informational purposes only.",
        analysis_confidence=0.9,
        warnings=[],
        is_valid_floor_plan=True,
    )
    return VastuAnalyzeResponse(
        data=data,
        report_markdown="# Vastu Report",
        has_warnings=False,
        warning_count=0,
        critical_warnings=False,
        provider_used="agnes",
        analyzed_at=utc_now_iso(),
    )


class TestVastuAnalyzeEndpoint:
    """Tests for POST /api/v1/vastu/analyze endpoint."""

    @pytest.mark.asyncio
    async def test_unusable_model_output_is_502_with_envelope(self, client: AsyncClient):
        """An unusable LLM result is a 502 in the shared error envelope, never a 200 or a 500."""
        from app.core.exceptions import ExternalServiceError

        with patch(
            "app.api.api_v1.endpoints.vastu.analyze_vastu",
            new_callable=AsyncMock,
            side_effect=ExternalServiceError(
                "The analysis service returned an unusable result. Please try again.",
                error_code="VASTU_UNUSABLE_OUTPUT",
            ),
        ):
            files = {
                "image": ("floor_plan.png", BytesIO(make_test_image_bytes("PNG")), "image/png")
            }
            response = await client.post(
                "/api/v1/vastu/analyze", files=files, data={"north_direction": "up"}
            )

        assert response.status_code == 502
        error = response.json()["error"]
        assert error["code"] == "VASTU_UNUSABLE_OUTPUT"
        assert "success" not in response.json()

    @pytest.mark.asyncio
    async def test_analyze_floor_plan_success(self, client: AsyncClient):
        """Test successful Vastu analysis."""
        with patch(
            "app.api.api_v1.endpoints.vastu.analyze_vastu",
            new_callable=AsyncMock,
        ) as mock_analyze:
            mock_analyze.return_value = create_mock_vastu_response(vastu_score=7)

            # Create test image data
            image_content = make_test_image_bytes("PNG")
            files = {"image": ("floor_plan.png", BytesIO(image_content), "image/png")}
            data = {
                "north_direction": "up",
                "provider": "gemini",
            }

            response = await client.post(
                "/api/v1/vastu/analyze",
                files=files,
                data=data,
            )

            assert response.status_code == 200
            resp_data = response.json()
            assert "success" not in resp_data
            assert resp_data["data"]["vastu_score"] == 7

    @pytest.mark.asyncio
    async def test_analyze_invalid_file_type(self, client: AsyncClient):
        """Test analysis with invalid file type."""
        file_content = b"not an image"
        files = {"image": ("test.txt", BytesIO(file_content), "text/plain")}
        data = {"north_direction": "up"}

        response = await client.post(
            "/api/v1/vastu/analyze",
            files=files,
            data=data,
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_analyze_empty_file(self, client: AsyncClient):
        """Test analysis with empty file."""
        files = {"image": ("empty.png", BytesIO(b""), "image/png")}
        data = {"north_direction": "up"}

        response = await client.post(
            "/api/v1/vastu/analyze",
            files=files,
            data=data,
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_analyze_corrupted_image_content(self, client: AsyncClient):
        """A file with an allowed content-type but undecodable bytes is rejected."""
        files = {"image": ("floor_plan.png", BytesIO(b"not actually a png" * 10), "image/png")}
        data = {"north_direction": "up"}

        response = await client.post(
            "/api/v1/vastu/analyze",
            files=files,
            data=data,
        )

        assert response.status_code == 400
        assert "Invalid or corrupted image" in response.json()["error"]["message"]

    @pytest.mark.asyncio
    async def test_analyze_invalid_north_direction(self, client: AsyncClient):
        """Test analysis with invalid north direction."""
        image_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        files = {"image": ("floor_plan.png", BytesIO(image_content), "image/png")}
        data = {"north_direction": "invalid_direction"}

        response = await client.post(
            "/api/v1/vastu/analyze",
            files=files,
            data=data,
        )

        assert response.status_code == 422
        assert "error" in response.json()

    @pytest.mark.asyncio
    async def test_analyze_invalid_provider(self, client: AsyncClient):
        """Test analysis with invalid AI provider."""
        image_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        files = {"image": ("floor_plan.png", BytesIO(image_content), "image/png")}
        data = {
            "north_direction": "up",
            "provider": "invalid_provider",
        }

        response = await client.post(
            "/api/v1/vastu/analyze",
            files=files,
            data=data,
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_analyze_notes_too_long(self, client: AsyncClient):
        """Test analysis with notes exceeding limit."""
        image_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        files = {"image": ("floor_plan.png", BytesIO(image_content), "image/png")}
        data = {
            "north_direction": "up",
            "notes": "x" * 1001,  # Exceeds 1000 char limit
        }

        response = await client.post(
            "/api/v1/vastu/analyze",
            files=files,
            data=data,
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_analyze_with_all_north_directions(self, client: AsyncClient):
        """Test analysis with various north directions."""
        with patch(
            "app.api.api_v1.endpoints.vastu.analyze_vastu",
            new_callable=AsyncMock,
        ) as mock_analyze:
            mock_analyze.return_value = create_mock_vastu_response(vastu_score=8)

            image_content = make_test_image_bytes("PNG")

            for direction in ["up", "down", "left", "right", "unknown"]:
                files = {"image": ("floor_plan.png", BytesIO(image_content), "image/png")}
                data = {"north_direction": direction}

                response = await client.post(
                    "/api/v1/vastu/analyze",
                    files=files,
                    data=data,
                )

                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_analyze_jpeg_image(self, client: AsyncClient):
        """Test analysis with JPEG image."""
        with patch(
            "app.api.api_v1.endpoints.vastu.analyze_vastu",
            new_callable=AsyncMock,
        ) as mock_analyze:
            mock_analyze.return_value = create_mock_vastu_response(vastu_score=6)

            image_content = make_test_image_bytes("JPEG")
            files = {"image": ("floor_plan.jpg", BytesIO(image_content), "image/jpeg")}
            data = {"north_direction": "up"}

            response = await client.post(
                "/api/v1/vastu/analyze",
                files=files,
                data=data,
            )

            assert response.status_code == 200


class TestVastuHealthEndpoint:
    """Tests for GET /api/v1/vastu/health endpoint."""

    @pytest.mark.asyncio
    async def test_vastu_health_check(self, client: AsyncClient):
        """Test Vastu service health check."""
        response = await client.get("/api/v1/vastu/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "vastu-analyzer"
        assert "providers" in data


@pytest.fixture(autouse=True)
def _no_vastu_rate_limit(test_app):
    """The 5/min limiter would trip across this file when CI uses a shared cache."""
    from app.api.api_v1.endpoints import vastu

    test_app.dependency_overrides[vastu._check_analyze_rate_limit] = lambda: None
    yield
    test_app.dependency_overrides.pop(vastu._check_analyze_rate_limit, None)
