"""
Route-table and response-validation guards for tour and scene endpoints.

- PATCH is the only update verb for tours, scenes and hotspots. The PUT aliases
  were removed (no client called them).
- POST /tours/{tour_id}/scenes/reorder is the only reorder verb.
- Response models validate ORM rows that hold scenes. Before the fix, the
  metadata alias read SQLAlchemy's MetaData object and every such response was a 500.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.factory import create_app
from app.models.tours import Scene as SceneModel
from app.models.tours import Tour as TourModel
from app.schemas.tour import Scene, TourWithScenes


def _methods_by_path(app) -> dict[str, set[str]]:
    """Collect the union of HTTP methods registered for each route path."""
    methods: dict[str, set[str]] = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            methods.setdefault(route.path, set()).update(route.methods or set())
    return methods


@pytest.fixture(scope="module")
def route_methods() -> dict[str, set[str]]:
    return _methods_by_path(create_app(testing=True))


# =============================================================================
# Route-table contract
# =============================================================================


def test_create_scene_route_is_not_shadowed(route_methods):
    """POST /tours/{tour_id}/scenes (scene creation) must remain a distinct route."""
    methods = route_methods.get("/api/v1/tours/{tour_id}/scenes", set())
    assert "POST" in methods, "POST /api/v1/tours/{tour_id}/scenes (create_scene) is missing"
    assert "GET" in methods, "GET /api/v1/tours/{tour_id}/scenes (list_scenes) is missing"


def test_update_routes_are_patch_only(route_methods):
    """PUT aliases on tour, scene and hotspot updates were removed."""
    assert "PATCH" in route_methods["/api/v1/tours/{tour_id}"]
    assert "PUT" not in route_methods["/api/v1/tours/{tour_id}"]
    assert "PATCH" in route_methods["/api/v1/scenes/{scene_id}"]
    assert "PUT" not in route_methods["/api/v1/scenes/{scene_id}"]
    assert "PATCH" in route_methods["/api/v1/hotspots/{hotspot_id}"]
    assert "PUT" not in route_methods["/api/v1/hotspots/{hotspot_id}"]


def test_reorder_scenes_is_post_only(route_methods):
    methods = route_methods.get("/api/v1/tours/{tour_id}/scenes/reorder", set())
    assert "POST" in methods
    assert "PUT" not in methods


# =============================================================================
# ORM rows validate (regression: be-tours-0 / branch-drift-0)
# =============================================================================

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _scene_row(scene_id: str = "scene-1", tour_id: str = "tour-1") -> SceneModel:
    scene = SceneModel(
        id=scene_id,
        tour_id=tour_id,
        title="Kitchen",
        image_url="https://res.cloudinary.com/demo/kitchen.jpg",
        order_index=0,
        scene_metadata={"initial_view": {"yaw": 10.0, "pitch": 0.0, "zoom": 50}},
        is_processed=True,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return scene


def test_scene_model_validates_orm_row_with_metadata():
    """Scene.model_validate on an ORM row returns its stored scene_metadata."""
    scene = Scene.model_validate(_scene_row())
    assert scene.scene_metadata is not None
    assert scene.scene_metadata.initial_view.yaw == 10.0


def test_tour_with_scenes_validates_orm_tour_with_a_scene():
    """The nested scene in a tour response validates (was a 500 for every tour with scenes)."""
    tour = TourModel(
        id="tour-1",
        user_id=1,
        title="Flat",
        status="draft",
        visibility="private",
        is_public=False,
        view_count=0,
        like_count=0,
        share_count=0,
        is_featured=False,
        created_at=_NOW,
        updated_at=_NOW,
    )
    tour.scenes = [_scene_row(tour_id="tour-1")]
    payload = TourWithScenes.model_validate(tour)
    assert payload.scenes[0].scene_metadata is not None
    assert "metadata" not in payload.model_dump()["scenes"][0]


def test_scene_response_wire_key_is_scene_metadata():
    """The wire key is the field name (no serialization alias)."""
    dumped = Scene.model_validate(_scene_row()).model_dump(mode="json")
    assert "scene_metadata" in dumped
    assert "metadata" not in dumped


# =============================================================================
# Request-level smoke test (routing + validation only; service layer mocked)
# =============================================================================

_TOUR_PAYLOAD = {
    "id": "tour-123",
    "user_id": 1,
    "title": "Updated Title",
    "description": None,
    "status": "draft",
    "is_public": False,
    "visibility": "private",
    "short_code": None,
    "is_featured": False,
    "view_count": 0,
    "like_count": 0,
    "share_count": 0,
    "settings": None,
    "thumbnail_url": None,
    "published_at": None,
    "archived_at": None,
    "created_at": _NOW,
    "updated_at": _NOW,
    "deleted_at": None,
    "scene_count": 0,
}


@pytest.fixture
def aliased_client():
    """TestClient with auth + db overridden and tour service update mocked."""
    from app.api.api_v1.dependencies.auth import get_current_active_user
    from app.core.database import get_db
    from app.schemas.user import User as UserSchema

    app = create_app(testing=True)

    user = UserSchema(
        id=1,
        supabase_user_id="00000000-0000-0000-0000-000000000001",
        role="user",
        is_active=True,
        is_verified=True,
        created_at=_NOW,
    )

    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: AsyncMock()

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    app.dependency_overrides.clear()


def test_update_tour_partial_body_routes_and_validates(aliased_client):
    """A partial PATCH body must not 405 (method missing) or 422 (validation)."""
    with patch(
        "app.services.tour.update_tour",
        new=AsyncMock(return_value=_TOUR_PAYLOAD),
    ) as mock_update:
        response = aliased_client.patch(
            "/api/v1/tours/tour-123",
            json={"title": "Updated Title"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Updated Title"
    mock_update.assert_awaited_once()


def test_put_on_tour_is_method_not_allowed(aliased_client):
    response = aliased_client.put("/api/v1/tours/tour-123", json={"title": "x"})
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
