"""
API tests for tour short share links.

Covers GET /v/{code} (200 + 404 paths), the refactored /share/tours/{tour_id}
route, and short-code assignment on publish.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import TourStatus, TourVisibility
from app.models.tours import Scene, Tour


async def _make_tour(
    db_session,
    user,
    *,
    status: TourStatus = TourStatus.published,
    is_public: bool = True,
    visibility: TourVisibility = TourVisibility.public,
    short_code: str | None = None,
) -> Tour:
    tour = Tour(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title="Shared Tour",
        status=status,
        is_public=is_public,
        visibility=visibility,
        short_code=short_code,
    )
    db_session.add(tour)
    scene = Scene(
        id=str(uuid.uuid4()),
        tour_id=tour.id,
        image_url="https://cdn.example.com/pano.jpg",
        order_index=0,
    )
    db_session.add(scene)
    await db_session.flush()
    return tour


class TestShortLink:
    @pytest.mark.asyncio
    async def test_short_link_renders_share_preview(self, guest_client, db_session, test_user):
        tour = await _make_tour(db_session, test_user, short_code="abc234")

        response = await guest_client.get("/v/abc234")

        assert response.status_code == 200
        assert "Shared Tour" in response.text
        assert f"/view/{tour.id}" in response.text
        assert 'property="og:title"' in response.text

    @pytest.mark.asyncio
    async def test_unknown_code_returns_404(self, guest_client, db_session, test_user):
        await _make_tour(db_session, test_user, short_code="abc234")

        response = await guest_client.get("/v/zzz999")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_unpublished_tour_returns_404(self, guest_client, db_session, test_user):
        await _make_tour(
            db_session,
            test_user,
            status=TourStatus.draft,
            is_public=False,
            visibility=TourVisibility.private,
            short_code="abc234",
        )

        response = await guest_client.get("/v/abc234")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_share_preview_route_still_works(self, guest_client, db_session, test_user):
        tour = await _make_tour(db_session, test_user)

        response = await guest_client.get(f"/share/tours/{tour.id}")

        assert response.status_code == 200
        assert "Shared Tour" in response.text

    @pytest.mark.asyncio
    async def test_unlisted_tour_is_shareable(self, guest_client, db_session, test_user):
        tour = await _make_tour(
            db_session,
            test_user,
            is_public=False,
            visibility=TourVisibility.unlisted,
            short_code="unlist",
        )

        response = await guest_client.get(f"/v/{tour.short_code}")

        assert response.status_code == 200
        assert "Shared Tour" in response.text

    @pytest.mark.asyncio
    async def test_private_tour_returns_404(self, guest_client, db_session, test_user):
        await _make_tour(
            db_session,
            test_user,
            is_public=False,
            visibility=TourVisibility.private,
            short_code="privat",
        )

        response = await guest_client.get("/v/privat")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_evil_redirect_is_ignored(self, guest_client, db_session, test_user):
        tour = await _make_tour(db_session, test_user, short_code="safe01")

        response = await guest_client.get(
            "/v/safe01?redirect=https://evil.example.com/phish"
        )

        assert response.status_code == 200
        assert "evil.example.com" not in response.text
        assert f"/view/{tour.id}" in response.text


class TestPublishAssignsShortCode:
    @pytest.mark.asyncio
    async def test_publish_sets_short_code_and_republish_keeps_it(
        self, user_client, db_session, test_user
    ):
        tour = await _make_tour(
            db_session,
            test_user,
            status=TourStatus.draft,
            is_public=False,
            visibility=TourVisibility.private,
        )

        response = await user_client.post(f"/api/v1/tours/{tour.id}/publish")
        assert response.status_code == 200
        short_code = response.json()["short_code"]
        assert short_code is not None
        assert len(short_code) == 6

        # Unpublish never clears the code; republish keeps the same one.
        response = await user_client.post(f"/api/v1/tours/{tour.id}/unpublish")
        assert response.status_code == 200
        assert response.json()["short_code"] == short_code

        response = await user_client.post(f"/api/v1/tours/{tour.id}/publish")
        assert response.status_code == 200
        assert response.json()["short_code"] == short_code
