"""BE-tours residual pass: the viewer event enum (be-tours-34) and the public scene page (be-tours-14).

Each test fails on the code as it stood before the residual pass.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.factory import create_app
from app.models.enums import TourEventType
from app.schemas.tour import TourEventPayload, ViewerEventType


def _event_type_values(schema: dict) -> set[str]:
    prop = schema["properties"]["event_type"]
    ref = prop.get("$ref") or prop.get("allOf", [{}])[0].get("$ref")
    if ref:
        return set(schema["$defs"][ref.rsplit("/", 1)[-1]]["enum"])
    return set(prop["enum"])


# be-tours-34: the spec lists the values a viewer may post, and nothing else.
def test_event_payload_spec_lists_only_the_viewer_event_types():
    values = _event_type_values(TourEventPayload.model_json_schema())

    assert values == {member.value for member in ViewerEventType}
    assert not values & {"view", "like", "unlike"}


def test_viewer_event_values_are_stored_event_types():
    for member in ViewerEventType:
        assert TourEventType(member.value) is not None


@pytest.mark.parametrize("event_type", ["view", "like", "unlike", "tour_view"])
def test_viewer_cannot_post_view_like_or_unknown_events(event_type: str):
    with pytest.raises(ValidationError):
        TourEventPayload.model_validate({"event_type": event_type})


# be-tours-14: the public scene list declares its response (no ORM passthrough).
def test_public_scenes_route_declares_the_public_scene_page():
    spec = create_app(testing=True).openapi()
    operation = spec["paths"]["/api/v1/public/tours/{tour_id}/scenes"]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]

    assert "$ref" in schema, schema
    page = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    item_ref = page["properties"]["items"]["items"]["$ref"]
    assert item_ref.endswith("/PublicScene")

    scene = spec["components"]["schemas"]["PublicScene"]["properties"]
    assert "scene_metadata" in scene
    assert "processing_error" not in scene
