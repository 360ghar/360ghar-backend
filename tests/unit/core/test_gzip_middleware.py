from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.infrastructure.middleware import register_middleware


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/big")
    def big() -> dict[str, list[str]]:
        return {"items": ["x" * 100] * 100}

    @app.get("/small")
    def small() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/sse")
    def sse() -> StreamingResponse:
        return StreamingResponse(iter(["data: " + "x" * 2000 + "\n\n"]), media_type="text/event-stream")

    register_middleware(app, testing=True)
    return app


def test_large_json_is_gzipped_small_json_and_sse_are_not() -> None:
    client = TestClient(_app())
    gzip = {"Accept-Encoding": "gzip"}
    assert client.get("/big", headers=gzip).headers.get("content-encoding") == "gzip"
    assert "content-encoding" not in client.get("/small", headers=gzip).headers
    assert "content-encoding" not in client.get("/sse", headers=gzip).headers
