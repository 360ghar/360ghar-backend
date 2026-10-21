"""
Tests for upload endpoints.
"""

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.exceptions import FileTooLargeException


class TestUploadFileEndpoint:
    """Tests for POST /api/v1/upload/ endpoint."""

    @pytest.mark.asyncio
    async def test_upload_file_success(self, authenticated_client: AsyncClient):
        """Test successful file upload."""
        with patch("app.api.api_v1.endpoints.upload.storage_service") as mock_storage:
            mock_storage.upload_and_track = AsyncMock(
                return_value={
                    "public_url": "https://storage.example.com/file.jpg",
                    "file_path": "360ghar/uploads/1/file.bin",
                    "file_type": "generic_upload",
                    "file_size": 17,
                    "content_type": "application/octet-stream",
                    "original_filename": "file.bin",
                    "media": None,
                }
            )

            # Create a test file
            file_content = b"test file content"
            files = {"file": ("test.jpg", BytesIO(file_content), "image/jpeg")}

            response = await authenticated_client.post(
                "/api/v1/upload/",
                files=files,
            )

            assert response.status_code == 201
            payload = response.json()
            assert payload["public_url"] == "https://storage.example.com/file.jpg"

    @pytest.mark.asyncio
    async def test_upload_file_unauthorized(self, client: AsyncClient):
        """Test upload without authentication."""
        file_content = b"test file content"
        files = {"file": ("test.jpg", BytesIO(file_content), "image/jpeg")}

        response = await client.post(
            "/api/v1/upload/",
            files=files,
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_upload_image_file(self, authenticated_client: AsyncClient):
        """Test uploading an image file."""
        with patch("app.api.api_v1.endpoints.upload.storage_service") as mock_storage:
            mock_storage.upload_and_track = AsyncMock(
                return_value={
                    "public_url": "https://storage.example.com/image.png",
                    "file_path": "360ghar/uploads/1/file.bin",
                    "file_type": "generic_upload",
                    "file_size": 17,
                    "content_type": "application/octet-stream",
                    "original_filename": "file.bin",
                    "media": None,
                    "mime_type": "image/png",
                }
            )

            file_content = b"\x89PNG\r\n\x1a\n"  # PNG header
            files = {"file": ("image.png", BytesIO(file_content), "image/png")}

            response = await authenticated_client.post(
                "/api/v1/upload/",
                files=files,
            )

            assert response.status_code == 201
            payload = response.json()
            assert payload["public_url"].endswith("image.png")

    @pytest.mark.asyncio
    async def test_upload_pdf_file(self, authenticated_client: AsyncClient):
        """Test uploading a PDF file."""
        with patch("app.api.api_v1.endpoints.upload.storage_service") as mock_storage:
            mock_storage.upload_and_track = AsyncMock(
                return_value={
                    "public_url": "https://storage.example.com/document.pdf",
                    "file_path": "360ghar/uploads/1/file.bin",
                    "file_type": "generic_upload",
                    "file_size": 17,
                    "content_type": "application/octet-stream",
                    "original_filename": "file.bin",
                    "media": None,
                    "mime_type": "application/pdf",
                }
            )

            file_content = b"%PDF-1.4"
            files = {"file": ("document.pdf", BytesIO(file_content), "application/pdf")}

            response = await authenticated_client.post(
                "/api/v1/upload/",
                files=files,
            )

            assert response.status_code == 201
            payload = response.json()
            assert payload["public_url"].endswith("document.pdf")

    @pytest.mark.asyncio
    async def test_upload_file_oversize_returns_413(self, authenticated_client: AsyncClient):
        """Test oversized direct upload surfaces as HTTP 413."""
        with patch("app.api.api_v1.endpoints.upload.storage_service") as mock_storage:
            mock_storage.upload_and_track = AsyncMock(
                side_effect=FileTooLargeException(detail="File too large. Maximum size is 50MB")
            )

            files = {"file": ("huge.jpg", BytesIO(b"oversize"), "image/jpeg")}
            response = await authenticated_client.post("/api/v1/upload/", files=files)

            assert response.status_code == 413
            assert response.json()["error"]["code"] == "FILE_TOO_LARGE"

    @pytest.mark.asyncio
    async def test_upload_batch_oversize_returns_413(self, authenticated_client: AsyncClient):
        """Test oversized batch member surfaces as HTTP 413."""
        with patch("app.api.api_v1.endpoints.upload.storage_service") as mock_storage:
            mock_storage.upload_batch = AsyncMock(
                side_effect=FileTooLargeException(detail="File too large. Maximum size is 50MB")
            )

            files = [("files", ("huge.jpg", BytesIO(b"oversize"), "image/jpeg"))]
            response = await authenticated_client.post("/api/v1/upload/batch", files=files)

            assert response.status_code == 413
            assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
