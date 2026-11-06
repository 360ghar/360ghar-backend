from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.infrastructure.middleware import register_middleware


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/big")
    def big():
        return {"items": ["x" * 100] * 100}

    @app.get("/sse")
    def sse():
        return StreamingResponse(iter(["data: " + "x" * 2000 + "\n\n"]), media_type="text/event-stream")

    register_middleware(app, testing=True)
    return app


def test_json_is_gzipped_and_sse_is_not():
    client = TestClient(_app())
    assert client.get("/big", headers={"Accept-Encoding": "gzip"}).headers.get("content-encoding") == "gzip"
    assert "content-encoding" not in client.get("/sse", headers={"Accept-Encoding": "gzip"}).headers
