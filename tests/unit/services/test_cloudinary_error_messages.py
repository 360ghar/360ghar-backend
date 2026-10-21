"""Cloudinary upload failures never send SDK text to the client."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import StorageException
from app.factory import create_app
from app.services.cloudinary.service import CloudinaryService

SDK_TEXT = "Invalid signature api_secret=abc123"


@pytest.fixture
def failing_service(monkeypatch) -> CloudinaryService:
    service = CloudinaryService()

    def boom(*args, **kwargs):
        raise RuntimeError(SDK_TEXT)

    monkeypatch.setattr(service._uploader, "upload", boom)
    return service


def test_upload_file_failure_uses_fixed_message(failing_service):
    with pytest.raises(StorageException) as exc_info:
        failing_service.upload_file(b"data", public_id="x")
    assert exc_info.value.detail == "Cloudinary upload failed"
    assert "abc123" not in exc_info.value.detail


def test_local_upload_failure_uses_fixed_message(failing_service):
    with pytest.raises(StorageException) as exc_info:
        failing_service.upload_local_file("/nonexistent/photo.jpg", public_id="x")
    assert exc_info.value.detail == "Cloudinary upload failed"


def test_url_upload_failure_uses_fixed_message(failing_service):
    with pytest.raises(StorageException) as exc_info:
        failing_service.upload_from_url("https://example.com/a.jpg", public_id="x")
    assert exc_info.value.detail == "Cloudinary upload from URL failed"


def test_envelope_hides_sdk_text_when_upload_fails(failing_service):
    app = create_app(testing=True)

    @app.post("/_contract/upload")
    async def upload():
        failing_service.upload_file(b"data", public_id="x")
        return {"ok": True}

    resp = TestClient(app, raise_server_exceptions=False).post("/_contract/upload")
    assert resp.status_code == 500
    assert resp.json() == {"error": {"code": "STORAGE_ERROR", "message": "Internal Server Error"}}
    assert "abc123" not in resp.text
