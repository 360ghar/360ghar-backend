"""Cursors are bound to request filters. A mismatched cursor gives 422 INVALID_CURSOR."""

from __future__ import annotations

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.core.exceptions import BadRequestException, ValidationException
from app.factory import create_app
from app.schemas.pagination import (
    CursorParams,
    build_cursor_page,
    decode_cursor,
    encode_cursor,
    filters_hash,
    offset_payload,
)


def test_cursor_round_trips_with_the_same_filters():
    cursor = encode_cursor(offset_payload(20), {"city": "Pune"})
    assert decode_cursor(cursor, {"city": "Pune"})["o"] == 20


def test_cursor_from_other_filters_is_422_invalid_cursor():
    cursor = encode_cursor(offset_payload(20), {"city": "Pune"})
    with pytest.raises(ValidationException) as exc:
        decode_cursor(cursor, {"city": "Delhi"})
    assert exc.value.status_code == 422
    assert exc.value.error_code == "INVALID_CURSOR"


def test_unbound_cursor_is_rejected_by_a_filtered_request():
    cursor = encode_cursor(offset_payload(20))
    with pytest.raises(ValidationException):
        decode_cursor(cursor, {"city": "Pune"})


def test_filter_key_order_does_not_change_the_hash():
    assert filters_hash({"a": 1, "b": 2}) == filters_hash({"b": 2, "a": 1})


def test_malformed_cursor_is_400_invalid_cursor():
    with pytest.raises(BadRequestException) as exc:
        decode_cursor("garbage!!!")
    assert exc.value.status_code == 400
    assert exc.value.error_code == "INVALID_CURSOR"


def test_build_cursor_page_binds_next_cursor_and_omits_total_by_default():
    page = build_cursor_page(
        [1, 2], limit=2, next_payload=offset_payload(2), filters={"city": "Pune"}
    )
    assert "total" not in page
    assert page["has_more"] is True
    assert decode_cursor(page["next_cursor"], {"city": "Pune"})["o"] == 2


def test_total_appears_only_when_given():
    page = build_cursor_page([], limit=2, next_payload=None, total=7)
    assert page["total"] == 7
    assert page["next_cursor"] is None
    assert page["has_more"] is False


def test_endpoint_rejects_a_cursor_from_other_filters():
    app = create_app(testing=True)

    @app.get("/_contract/cursor")
    async def cursor_route(city: str = "Pune", page: CursorParams = Depends()):
        page.decoded({"city": city})
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    cursor = encode_cursor(offset_payload(20), {"city": "Pune"})

    assert (
        client.get("/_contract/cursor", params={"cursor": cursor, "city": "Pune"}).status_code
        == 200
    )

    bad = client.get("/_contract/cursor", params={"cursor": cursor, "city": "Delhi"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "INVALID_CURSOR"
