"""Global exception handler maps transient DB errors to 503."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.infrastructure.errors import register_exception_handlers


@pytest.mark.asyncio
async def test_transient_db_error_returns_503_not_500() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise Exception(
            "(psycopg.errors.InternalError_) (ECHECKOUTTIMEOUT) "
            "unable to check out connection from the pool after 60000ms "
            "in Transaction mode"
        )

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/boom")

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert body["error"]["details"]["error_code"] == "ECHECKOUTTIMEOUT"
    assert response.headers.get("retry-after") == "5"


@pytest.mark.asyncio
async def test_edbhandler_exited_returns_503() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/closed")
    async def closed():
        raise Exception(
            "(psycopg.errors.InternalError_) (EDBHANDLEREXITED) "
            "connection to database closed. Check logs for more information"
        )

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/closed")

    assert response.status_code == 503
    assert response.json()["error"]["details"]["error_code"] == "EDBHANDLEREXITED"


@pytest.mark.asyncio
async def test_non_transient_error_still_500() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/bug")
    async def bug():
        raise RuntimeError("unexpected programming error")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/bug")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"


@pytest.mark.asyncio
async def test_ssl_eof_returns_503() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/ssl")
    async def ssl_fail():
        raise Exception(
            "(psycopg.OperationalError) consuming input failed: "
            "SSL error: unexpected eof while reading"
        )

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ssl")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_detached_instance_returns_stable_code() -> None:
    from sqlalchemy.orm.exc import DetachedInstanceError

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/detached")
    async def detached():
        raise DetachedInstanceError(
            "Instance <User at 0x1> is not bound to a Session; "
            "attribute refresh operation cannot proceed"
        )

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/detached")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "DETACHED_ORM_INSTANCE"


def _header_app() -> FastAPI:
    from fastapi import HTTPException

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/limited")
    async def limited():
        raise HTTPException(status_code=429, detail="Slow down", headers={"Retry-After": "17"})

    @app.get("/coded")
    async def coded():
        raise HTTPException(
            status_code=503, detail={"code": "BUSY", "message": "Busy"}, headers={"Retry-After": "9"}
        )

    @app.post("/mcp/oauth/token")
    async def oauth_token():
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_grant", "error_description": "bad code"},
            headers={"Cache-Control": "no-store"},
        )

    return app


@pytest.mark.asyncio
async def test_http_exception_keeps_retry_after_and_standard_body() -> None:
    transport = ASGITransport(app=_header_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        limited = await client.get("/limited")
        coded = await client.get("/coded")

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "17"
    assert limited.json() == {"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Slow down"}}
    assert coded.status_code == 503
    assert coded.headers["retry-after"] == "9"
    assert coded.json() == {"error": {"code": "BUSY", "message": "Busy"}}


@pytest.mark.asyncio
async def test_oauth_http_exception_is_unchanged() -> None:
    transport = ASGITransport(app=_header_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/mcp/oauth/token")

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_grant", "error_description": "bad code"}
    assert response.headers["cache-control"] == "no-store"
