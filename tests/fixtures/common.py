"""
Shared assertion helpers and DB seeding utilities for tests.
"""

from typing import Any

from httpx import Response

# =============================================================================
# Assertion Helpers
# =============================================================================

def assert_has_keys(data: dict[str, Any], keys: list[str]) -> None:
    """Assert that dict contains all specified keys."""
    missing = set(keys) - set(data.keys())
    assert not missing, f"Missing keys: {missing}"


def assert_status(response: Response, expected: int, msg: str = "") -> None:
    """Assert response status code matches expected."""
    assert response.status_code == expected, (
        f"Expected {expected}, got {response.status_code}. "
        f"Body: {response.text}. {msg}"
    )


def assert_paginated(response: Response, *, min_items: int = 0) -> dict[str, Any]:
    """Assert paginated response shape and return data."""
    data = response.json()
    assert "items" in data or "total" in data, f"Missing pagination keys: {list(data.keys())}"
    if "items" in data:
        assert len(data["items"]) >= min_items, f"Expected >= {min_items} items, got {len(data['items'])}"
    return data


def assert_validation_error(response: Response, field: str | None = None) -> None:
    """Assert response is a 422 validation error, optionally for a specific field."""
    assert response.status_code == 422, f"Expected 422, got {response.status_code}"
    body = response.json()
    assert "detail" in body
    if field:
        fields_in_error = [e.get("loc", [])[-1] for e in body["detail"] if isinstance(e, dict)]
        assert field in fields_in_error, f"Field '{field}' not in error locations: {fields_in_error}"


def assert_not_found(response: Response) -> None:
    """Assert response is 404."""
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"


def assert_unauthorized(response: Response) -> None:
    """Assert response is 401."""
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"


def assert_forbidden(response: Response) -> None:
    """Assert response is 403."""
    assert response.status_code == 403, f"Expected 403, got {response.status_code}"
