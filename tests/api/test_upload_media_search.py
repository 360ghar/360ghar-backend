"""GET /api/v1/upload/media: search filter bound to the cursor, and routing guards.

The database is real. Storage is not touched by these routes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tours import MediaFile

pytestmark = pytest.mark.asyncio

MEDIA = "/api/v1/upload/media"


def _media(user_id: int, name: str, minutes_ago: int) -> MediaFile:
    return MediaFile(
        id=str(uuid.uuid4()),
        user_id=user_id,
        filename=name,
        original_filename=name,
        file_url=f"https://res.cloudinary.com/example/image/upload/v1/{name}",
        file_size=1024,
        mime_type="image/jpeg",
        folder="uploads",
        visibility="private",
        is_processed=False,
        upload_status="complete",
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession, test_user):
    # Newest first: kitchen-2, bath, kitchen-1.
    rows = [
        _media(test_user.id, "kitchen-1.jpg", 30),
        _media(test_user.id, "bath.jpg", 20),
        _media(test_user.id, "kitchen-2.jpg", 10),
    ]
    db_session.add_all(rows)
    await db_session.flush()
    return rows


async def test_search_matches_the_filename_and_pages_through_the_cursor(
    authenticated_client: AsyncClient, seeded
):
    first = await authenticated_client.get(MEDIA, params={"search": "kitchen", "limit": 1})
    assert first.status_code == 200, first.text
    body = first.json()
    assert [item["original_filename"] for item in body["items"]] == ["kitchen-2.jpg"]
    assert body["has_more"] is True
    assert body["next_cursor"]

    second = await authenticated_client.get(
        MEDIA, params={"search": "kitchen", "limit": 1, "cursor": body["next_cursor"]}
    )
    assert second.status_code == 200, second.text
    page = second.json()
    assert [item["original_filename"] for item in page["items"]] == ["kitchen-1.jpg"]
    assert page["has_more"] is False


async def test_search_excludes_files_that_do_not_match(authenticated_client: AsyncClient, seeded):
    response = await authenticated_client.get(MEDIA, params={"search": "kitchen", "limit": 10})
    assert response.status_code == 200, response.text
    names = [item["original_filename"] for item in response.json()["items"]]
    assert names == ["kitchen-2.jpg", "kitchen-1.jpg"]


async def test_cursor_from_a_search_is_rejected_for_another_search(
    authenticated_client: AsyncClient, seeded
):
    first = await authenticated_client.get(MEDIA, params={"search": "kitchen", "limit": 1})
    cursor = first.json()["next_cursor"]
    assert cursor

    response = await authenticated_client.get(
        MEDIA, params={"search": "bath", "limit": 1, "cursor": cursor}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CURSOR"


async def test_search_is_a_literal_substring_not_a_pattern(
    authenticated_client: AsyncClient, seeded
):
    response = await authenticated_client.get(MEDIA, params={"search": "%", "limit": 10})
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_uploads_path_is_not_mounted_and_no_local_fallback_is_imported():
    import importlib.util
    import sys

    from app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    assert not any(path.startswith(("/uploads", "/api/v1/uploads")) for path in paths)
    assert importlib.util.find_spec("app.services.storage.local_fallback") is None
    assert not any("local_fallback" in name for name in sys.modules)
