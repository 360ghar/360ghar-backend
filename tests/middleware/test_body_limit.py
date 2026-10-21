"""BodyLimitMiddleware answers 413 before the body is buffered."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.middleware.body_limit import BodyLimitMiddleware


async def _echo(request: Request) -> JSONResponse:
    body = await request.body()
    return JSONResponse({"size": len(body)})


def _app() -> Starlette:
    app = Starlette(routes=[Route("/limited", _echo, methods=["POST"]), Route("/free", _echo, methods=["POST"])])
    app.add_middleware(BodyLimitMiddleware, limits={"/limited": 100})
    return app


@pytest.mark.asyncio
async def test_declared_length_over_cap_gets_413():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        resp = await c.post("/limited", content=b"x" * 101)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


@pytest.mark.asyncio
async def test_body_within_cap_and_other_paths_pass():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        ok = await c.post("/limited", content=b"x" * 100)
        free = await c.post("/free", content=b"x" * 1000)
    assert ok.json() == {"size": 100}
    assert free.json() == {"size": 1000}


@pytest.mark.asyncio
async def test_chunked_body_over_cap_gets_413():
    async def chunks():
        for _ in range(5):
            yield b"x" * 30

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        resp = await c.post("/limited", content=chunks())
    assert resp.status_code == 413
