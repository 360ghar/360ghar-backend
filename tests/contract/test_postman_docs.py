"""Guards the Postman collections against requests the backend no longer serves.

Each check names the wire change it protects (changelog/BE-notify.md, residual
round 2). The collections are documentation. A stale request fails with 404, 422
or 4001 when a developer runs it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest

POSTMAN_DIR = Path(__file__).resolve().parents[2] / "docs" / "postman"
COLLECTIONS = ("postman-collection.json", "admin-dashboard-collection.json")

# Declared query keys of GET /api/v1/upload/media. Any other key is a 422.
MEDIA_LIST_QUERY_KEYS = {
    "cursor",
    "limit",
    "include_total",
    "tour_id",
    "mime_type",
    "visibility",
    "is_processed",
    "upload_status",
    "search",
}

# folder_type values that /upload/batch refuses (FOLDER_TYPE_NOT_ALLOWED).
BATCH_REFUSED_FOLDER_TYPES = {"property_image", "property_video", "property_document", "scene"}

Case = tuple[str, dict[str, Any]]


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((POSTMAN_DIR / name).read_text(encoding="utf-8"))
    return data


def _request_items(node: Any) -> list[dict[str, Any]]:
    """Return every item that carries a request, at any folder depth."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if isinstance(node.get("request"), dict):
            found.append(node)
        for child in node.get("item", []) or []:
            found.extend(_request_items(child))
    elif isinstance(node, list):
        for child in node:
            found.extend(_request_items(child))
    return found


def _cases(keep: Callable[[str, dict[str, Any]], bool]) -> list[Case]:
    """Every (collection, item) pair whose request satisfies keep(raw_url, request)."""
    cases: list[Case] = []
    for name in COLLECTIONS:
        for item in _request_items(_load(name)):
            request = item["request"]
            if keep(_raw_url(request), request):
                cases.append((name, item))
    return cases


def _ids(cases: list[Case]) -> list[str]:
    return [f"{name}::{item.get('name', '?')}" for name, item in cases]


def _raw_url(request: dict[str, Any]) -> str:
    url = request.get("url")
    if isinstance(url, dict):
        return str(url.get("raw", ""))
    return str(url or "")


def _query_keys(raw: str) -> list[str]:
    return [key for key, _ in parse_qsl(urlsplit(raw).query, keep_blank_values=True)]


ALL_CASES = _cases(lambda raw, request: True)
WS_CASES = _cases(lambda raw, request: "/ws/" in raw)
UNREGISTER_CASES = _cases(lambda raw, request: "/devices/unregister" in raw)
MEDIA_LIST_CASES = _cases(lambda raw, request: urlsplit(raw).path.endswith("/upload/media"))
BATCH_CASES = _cases(lambda raw, request: urlsplit(raw).path.endswith("/upload/batch"))


@pytest.mark.parametrize("collection, item", ALL_CASES, ids=_ids(ALL_CASES))
def test_no_request_puts_a_token_in_the_query_string(collection: str, item: dict[str, Any]) -> None:
    """Browsers and proxies log query strings. Tokens go in the first WebSocket frame."""
    raw = _raw_url(item["request"])
    assert "token=" not in raw, f"{collection}: {item.get('name')} carries a token in the URL"


@pytest.mark.parametrize("collection, item", WS_CASES, ids=_ids(WS_CASES))
def test_websocket_requests_have_no_query_and_describe_the_first_frame(
    collection: str, item: dict[str, Any]
) -> None:
    request = item["request"]
    assert _query_keys(_raw_url(request)) == [], (
        f"{collection}: {item.get('name')} has a query string"
    )
    description = str(request.get("description") or item.get("description") or "")
    assert '"type": "auth"' in description, f"{collection}: {item.get('name')} omits the auth frame"
    assert "query param" not in description.lower()


def test_no_collection_mentions_the_removed_tour_socket() -> None:
    """/ws/tours/{tour_id} was removed. No client connects to it."""
    for name in COLLECTIONS:
        text = (POSTMAN_DIR / name).read_text(encoding="utf-8")
        assert "/ws/tours" not in text, f"{name} still documents /ws/tours"


def test_no_collection_calls_the_removed_deeplink_routes() -> None:
    """GET /deeplinks/apps, POST /deeplinks/generate and the resolve route are removed."""
    for name in COLLECTIONS:
        text = (POSTMAN_DIR / name).read_text(encoding="utf-8")
        assert "/api/v1/deeplinks" not in text, f"{name} calls a removed deeplink route"


@pytest.mark.parametrize("collection, item", UNREGISTER_CASES, ids=_ids(UNREGISTER_CASES))
def test_device_unregister_sends_the_token_in_the_body(
    collection: str, item: dict[str, Any]
) -> None:
    """DELETE /devices/unregister takes {"token": ...} in a JSON body (BE-notify)."""
    request = item["request"]
    assert _query_keys(_raw_url(request)) == [], (
        f"{collection}: {item.get('name')} still sends a query string"
    )
    body = request.get("body") or {}
    assert body.get("mode") == "raw", f"{collection}: {item.get('name')} has no JSON body"
    assert '"token"' in str(body.get("raw", "")), f"{collection}: body lacks the token key"


@pytest.mark.parametrize("collection, item", MEDIA_LIST_CASES, ids=_ids(MEDIA_LIST_CASES))
def test_media_list_uses_only_declared_query_keys(collection: str, item: dict[str, Any]) -> None:
    """An undeclared query key is a 422 on every route. page, page_size and folder are gone."""
    stray = set(_query_keys(_raw_url(item["request"]))) - MEDIA_LIST_QUERY_KEYS
    assert not stray, f"{collection}: {item.get('name')} sends undeclared keys {sorted(stray)}"


@pytest.mark.parametrize("collection, item", BATCH_CASES, ids=_ids(BATCH_CASES))
def test_batch_upload_sends_folder_type_and_no_refused_value(
    collection: str, item: dict[str, Any]
) -> None:
    request = item["request"]
    fields = {f.get("key"): f.get("value") for f in (request.get("body") or {}).get("formdata", [])}
    assert "folder" not in fields, (
        f"{collection}: {item.get('name')} sends the removed folder field"
    )
    assert "folder_type" in fields, f"{collection}: {item.get('name')} omits folder_type"
    assert fields["folder_type"] not in BATCH_REFUSED_FOLDER_TYPES, (
        f"{collection}: {item.get('name')} sends a folder_type that /upload/batch refuses"
    )
