"""Tests for ETagMiddleware: weak ETags and 304 Not Modified on GET JSON."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.middleware.cache_control import CacheControlMiddleware
from app.middleware.etag import ETagMiddleware, etag_matches, make_etag


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CacheControlMiddleware)
    app.add_middleware(ETagMiddleware)

    @app.get("/api/v1/properties/list")
    async def properties_list():
        return {"items": [1, 2]}

    @app.post("/api/v1/items")
    async def create_item():
        return {"id": 1}

    @app.get("/api/v1/text")
    async def text():
        return PlainTextResponse("hello")

    @app.get("/api/v1/sse")
    async def sse():
        async def gen():
            yield "data: x\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/v1/missing")
    async def missing():
        return JSONResponse({"error": "nope"}, status_code=404)

    @app.get("/api/v1/tagged")
    async def tagged():
        return JSONResponse({"a": 1}, headers={"ETag": '"custom"'})

    @app.api_route("/api/v1/both", methods=["GET", "HEAD"])
    async def both():
        return {"a": 1}

    @app.get("/api/v1/varied")
    async def varied():
        return JSONResponse({"a": 1}, headers={"Vary": "Accept-Encoding"})

    @app.get("/outside")
    async def outside():
        return {"a": 1}

    return app


async def _get(path: str, method: str = "GET", **headers: str):
    transport = ASGITransport(app=_make_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers)


def test_etag_helpers():
    tag = make_etag(b'{"a":1}')
    assert tag.startswith('W/"') and tag.endswith('"')
    assert tag == make_etag(b'{"a":1}')
    assert tag != make_etag(b'{"a":2}')
    strong = tag.removeprefix("W/")
    assert etag_matches(tag, tag)
    assert etag_matches(strong, tag)  # weak comparison ignores W/
    assert etag_matches(f'"other", {strong} ,W/"x"', tag)
    assert etag_matches("*", tag)
    assert not etag_matches('"other", W/"x"', tag)
    assert not etag_matches("", tag)


@pytest.mark.asyncio
async def test_200_json_gets_weak_etag():
    resp = await _get("/api/v1/properties/list")
    assert resp.status_code == 200
    assert resp.headers["etag"] == make_etag(resp.content)
    assert resp.json() == {"items": [1, 2]}


@pytest.mark.asyncio
async def test_matching_if_none_match_returns_304_with_empty_body():
    first = await _get("/api/v1/properties/list", authorization="Bearer t")
    etag = first.headers["etag"]

    resp = await _get(
        "/api/v1/properties/list", authorization="Bearer t", **{"if-none-match": f'"x", {etag}'}
    )
    assert resp.status_code == 304
    assert resp.content == b""
    assert resp.headers["etag"] == etag
    assert resp.headers["cache-control"] == "private, no-store"
    assert "Authorization" in resp.headers["vary"]
    assert "content-type" not in resp.headers
    assert resp.headers.get("content-length") in (None, "0")


@pytest.mark.asyncio
async def test_star_and_strong_form_also_match():
    etag = (await _get("/api/v1/properties/list")).headers["etag"]
    assert (await _get("/api/v1/properties/list", **{"if-none-match": "*"})).status_code == 304
    strong = etag.removeprefix("W/")
    assert (await _get("/api/v1/properties/list", **{"if-none-match": strong})).status_code == 304


@pytest.mark.asyncio
async def test_non_matching_if_none_match_returns_200():
    resp = await _get("/api/v1/properties/list", **{"if-none-match": 'W/"stale"'})
    assert resp.status_code == 200
    assert resp.json() == {"items": [1, 2]}
    assert resp.headers["etag"] == make_etag(resp.content)


@pytest.mark.asyncio
async def test_head_gets_same_etag_as_get():
    get = await _get("/api/v1/both")
    head = await _get("/api/v1/both", method="HEAD")
    assert head.status_code == 200
    assert head.headers.get("etag") == get.headers["etag"]
    assert (await _get("/api/v1/both", method="HEAD", **{"if-none-match": get.headers["etag"]})).status_code == 304


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("POST", "/api/v1/items", 200),
        ("GET", "/api/v1/text", 200),
        ("GET", "/api/v1/sse", 200),
        ("GET", "/api/v1/missing", 404),
        ("GET", "/outside", 200),
    ],
)
async def test_untouched_responses(method, path, status):
    resp = await _get(path, method=method, **{"if-none-match": "*"})
    assert resp.status_code == status
    assert "etag" not in resp.headers


@pytest.mark.asyncio
async def test_existing_etag_is_kept():
    resp = await _get("/api/v1/tagged", **{"if-none-match": "*"})
    assert resp.status_code == 200
    assert resp.headers["etag"] == '"custom"'


def test_registered_in_app_and_304_keeps_cache_headers():
    from app.factory import create_app

    app = create_app(testing=True)

    @app.get("/api/v1/amenities_etag_probe")
    async def probe():
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    first = client.get("/api/v1/amenities_etag_probe")
    assert first.status_code == 200
    etag = first.headers["etag"]

    second = client.get("/api/v1/amenities_etag_probe", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["etag"] == etag
    assert second.headers["cache-control"].startswith("public")
    assert "vary" in second.headers


@pytest.mark.asyncio
async def test_etag_responses_vary_on_authorization():
    first = await _get("/api/v1/both")
    assert first.status_code == 200
    assert first.headers["vary"] == "Authorization"

    second = await _get("/api/v1/both", **{"if-none-match": first.headers["etag"]})
    assert second.status_code == 304
    assert second.headers["vary"] == "Authorization"


@pytest.mark.asyncio
async def test_existing_vary_gets_authorization_merged_into_one_header():
    resp = await _get("/api/v1/varied")
    assert resp.headers["vary"] == "Accept-Encoding, Authorization"
