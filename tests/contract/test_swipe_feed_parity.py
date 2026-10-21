"""GET /swipes takes the same query keys as GET /properties, plus the swipe-only is_liked."""

from __future__ import annotations

from app.factory import create_app

# The swipe feed is built from the shared property filter dependency. It rejects
# semantic_search and exclude_swiped when they are true (see the endpoint).
SWIPE_ONLY = {"is_liked"}


def _query_keys(spec: dict, path: str) -> set[str]:
    operation = spec["paths"][path]["get"]
    return {param["name"] for param in operation.get("parameters", []) if param["in"] == "query"}


def test_swipe_feed_and_property_list_take_the_same_query_keys():
    spec = create_app(testing=True).openapi()

    swipes = _query_keys(spec, "/api/v1/swipes")
    properties = _query_keys(spec, "/api/v1/properties")

    assert swipes - properties == SWIPE_ONLY
    assert properties - swipes == set()
