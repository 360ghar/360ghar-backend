"""Every non-2xx JSON response uses {"error": {"code", "message", "details"?}}."""

from __future__ import annotations

from fastapi import HTTPException, Query
from fastapi.testclient import TestClient
from pydantic import Field
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.api.api_v1.dependencies import query_params
from app.core.exceptions import (
    ExternalServiceError,
    ForbiddenException,
    RateLimitException,
    ServiceUnavailableException,
    StorageException,
    UnauthorizedException,
)
from app.factory import create_app
from app.infrastructure import errors
from app.middleware.rate_limit import RateLimitMiddleware
from app.schemas.base import WriteModel


class Price(WriteModel):
    price: int = Field(gt=0)


def _client(configure=None) -> TestClient:
    app = create_app(testing=True)
    if configure:
        configure(app)
    return TestClient(app, raise_server_exceptions=False)


def _routes(app) -> None:
    @app.get("/_contract/unauthorized")
    async def unauthorized():
        raise UnauthorizedException("Token expired")

    @app.get("/_contract/unauthorized-dict")
    async def unauthorized_dict():
        raise HTTPException(
            status_code=401,
            detail={"code": "TOKEN_INVALID", "message": "Invalid token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.get("/_contract/forbidden")
    async def forbidden():
        raise ForbiddenException("No access")

    @app.get("/_contract/conflict")
    async def conflict():
        raise HTTPException(
            status_code=409,
            detail={"code": "DUPLICATE_SWIPE", "message": "Already swiped", "existing_id": 7},
        )

    @app.post("/_contract/body")
    async def body(payload: Price):
        return {"ok": True}

    @app.get("/_contract/query")
    async def query(n: int = Query(...)):
        return {"n": n}

    @app.get("/_contract/rate-limited")
    async def rate_limited():
        raise RateLimitException("Slow down", headers={"Retry-After": "60"})

    @app.get("/_contract/boom")
    async def boom():
        raise RuntimeError("db password is hunter2")

    @app.get("/_contract/unavailable")
    async def unavailable():
        raise ServiceUnavailableException(
            detail="Recommendations unavailable", details={"error_code": "X1"}
        )

    @app.get("/_contract/value-error")
    async def value_error():
        raise ValueError("secret input leaked here")


def test_401_uses_envelope_and_keeps_www_authenticate():
    resp = _client(_routes).get("/_contract/unauthorized")
    assert resp.status_code == 401
    assert resp.json() == {"error": {"code": "UNAUTHORIZED", "message": "Token expired"}}
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_401_dict_detail_keeps_its_code():
    resp = _client(_routes).get("/_contract/unauthorized-dict")
    assert resp.status_code == 401
    assert resp.json() == {"error": {"code": "TOKEN_INVALID", "message": "Invalid token"}}
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_403_uses_envelope():
    resp = _client(_routes).get("/_contract/forbidden")
    assert resp.status_code == 403
    assert resp.json() == {"error": {"code": "FORBIDDEN", "message": "No access"}}


def test_404_unknown_route_uses_envelope():
    resp = _client().get("/api/v1/this-route-does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert "detail" not in body


def test_405_uses_envelope():
    resp = _client().post("/api/v1/health")
    assert resp.status_code == 405
    assert resp.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_409_dict_detail_moves_extra_keys_into_details():
    resp = _client(_routes).get("/_contract/conflict")
    assert resp.status_code == 409
    assert resp.json() == {
        "error": {
            "code": "DUPLICATE_SWIPE",
            "message": "Already swiped",
            "details": {"existing_id": 7},
        }
    }


def test_422_body_lists_dotted_field_names():
    resp = _client(_routes).post("/_contract/body", json={"price": 0, "extra": 1})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed"
    fields = {entry["field"]: entry for entry in body["error"]["details"]["fields"]}
    assert set(fields) == {"body.price", "body.extra"}
    assert fields["body.price"]["type"] == "greater_than"
    assert fields["body.extra"]["type"] == "extra_forbidden"
    assert set(fields["body.price"]) == {"field", "msg", "type"}


def test_422_query_uses_query_prefix():
    resp = _client(_routes).get("/_contract/query", params={"n": "abc"})
    assert resp.status_code == 422
    assert [e["field"] for e in resp.json()["error"]["details"]["fields"]] == ["query.n"]


def test_429_from_raise_keeps_retry_after():
    resp = _client(_routes).get("/_contract/rate-limited")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert resp.headers.get("retry-after") == "60"


def test_429_from_middleware_uses_envelope(monkeypatch):
    async def always_limited(self, client_id, path):  # noqa: ARG001
        return False

    monkeypatch.setattr(RateLimitMiddleware, "check_rate_limit", always_limited)

    app = Starlette(routes=[Route("/limited", lambda request: PlainTextResponse("ok"))])
    app.add_middleware(RateLimitMiddleware, calls=1, period=60, scope="test")
    resp = TestClient(app).get("/limited")

    assert resp.status_code == 429
    assert resp.json() == {
        "error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Rate limit exceeded"}
    }
    assert resp.headers.get("retry-after") == "60"


def test_500_hides_exception_text():
    resp = _client(_routes).get("/_contract/boom")
    assert resp.status_code == 500
    assert resp.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"}
    }
    assert "hunter2" not in resp.text


def test_5xx_from_storage_error_shows_status_phrase_not_exception_text():
    def configure(app):
        @app.get("/_contract/storage")
        async def storage():
            raise StorageException(detail="Cloudinary upload failed: sdk says api_secret=abc")

        @app.get("/_contract/raw-502")
        async def raw_502():
            raise HTTPException(status_code=502, detail="upstream says token=xyz")

    client = _client(configure)
    resp = client.get("/_contract/storage")
    assert resp.status_code == 500
    assert resp.json() == {"error": {"code": "STORAGE_ERROR", "message": "Internal Server Error"}}

    raw = client.get("/_contract/raw-502")
    assert raw.status_code == 502
    assert raw.json()["error"]["message"] == "Bad Gateway"
    assert "xyz" not in raw.text


def test_5xx_curated_exceptions_keep_their_message():
    def configure(app):
        @app.get("/_contract/external")
        async def external():
            raise ExternalServiceError(detail="Invalid Perplexity response")

    resp = _client(configure).get("/_contract/external")
    assert resp.status_code == 502
    assert resp.json()["error"]["message"] == "Invalid Perplexity response"


def test_5xx_auth_dict_detail_with_curated_code_keeps_its_message():
    def configure(app):
        @app.get("/_contract/auth-unreachable")
        async def auth_unreachable():
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "AUTH_PROVIDER_UNREACHABLE",
                    "message": "Authentication provider is temporarily unreachable, please retry",
                },
                headers={"Retry-After": "30"},
            )

    resp = _client(configure).get("/_contract/auth-unreachable")
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "30"
    assert resp.json()["error"] == {
        "code": "AUTH_PROVIDER_UNREACHABLE",
        "message": "Authentication provider is temporarily unreachable, please retry",
    }


def test_503_keeps_details_and_envelope():
    resp = _client(_routes).get("/_contract/unavailable")
    assert resp.status_code == 503
    assert resp.json() == {
        "error": {
            "code": "SERVICE_UNAVAILABLE",
            "message": "Recommendations unavailable",
            "details": {"error_code": "X1"},
        }
    }


def test_503_for_transient_db_failure_retries_after_five_seconds(monkeypatch):
    monkeypatch.setattr(errors, "is_retryable_read_db_error", lambda exc: True)
    monkeypatch.setattr(errors, "read_db_error_code", lambda exc: "ECHECKOUTTIMEOUT")

    resp = _client(_routes).get("/_contract/boom")
    assert resp.status_code == 503
    body = resp.json()["error"]
    assert body["code"] == "SERVICE_UNAVAILABLE"
    assert body["details"] == {"error_code": "ECHECKOUTTIMEOUT", "endpoint": "/_contract/boom"}
    assert resp.headers.get("retry-after") == "5"


def test_value_error_gets_fixed_422_message_and_no_input_text():
    resp = _client(_routes).get("/_contract/value-error")
    assert resp.status_code == 422
    assert resp.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Invalid request",
            "details": {"fields": []},
        }
    }
    assert "secret input" not in resp.text


def test_every_422_carries_details_fields():
    """The 422 body is ValidationErrorEnvelope: a domain 422 without fields gets an empty list."""
    from app.core.exceptions import ValidationException

    def routes(app) -> None:
        @app.get("/_contract/domain-422")
        async def domain_422():
            raise ValidationException("Cursor mismatch", error_code="INVALID_CURSOR")

        @app.get("/_contract/domain-422-fields")
        async def domain_422_fields():
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "X",
                    "message": "m",
                    "fields": [{"field": "body.a", "msg": "bad", "type": "t"}],
                },
            )

    client = _client(routes)
    bare = client.get("/_contract/domain-422").json()["error"]
    assert bare["code"] == "INVALID_CURSOR"
    assert bare["details"] == {"fields": []}
    kept = client.get("/_contract/domain-422-fields").json()["error"]
    assert kept["details"]["fields"] == [{"field": "body.a", "msg": "bad", "type": "t"}]


def test_envelope_builder_omits_empty_details():
    assert errors.error_body("X", "m") == {"error": {"code": "X", "message": "m"}}
    assert errors.error_body("X", "m", {"a": 1}) == {
        "error": {"code": "X", "message": "m", "details": {"a": 1}}
    }


def test_strict_query_dependency_is_attached_to_api_router():
    from app.api.api_v1.api import api_router

    assert any(
        dep.dependency is query_params.reject_unknown_query_params
        for dep in api_router.dependencies
    )
