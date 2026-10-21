"""Content endpoints: public reads, the cron-protected run, and the admin review queue."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models.content import ContentBlock
from app.services.content import runner
from tests.fixtures.content import FakeProvider, compose

pytestmark = pytest.mark.asyncio

BODY = {"summary": "s", "highlights": [], "faqs": [], "meta_description": "m"}
CRON = {"X-Cron-Secret": "s3cret-value"}


def block(slug: str, status: str = "auto", locale: str = "en", **kw) -> ContentBlock:
    return ContentBlock(
        entity_type=kw.pop("entity_type", "locality"), slug=slug, locale=locale, body=BODY,
        facts_hash="h", prompt_version="v1", review_status=status, fact_count=kw.pop("fact_count", 7),
        key_fact=kw.pop("key_fact", True), indexable=kw.pop("indexable", True), **kw,
    )


@pytest.fixture
def cron_secret(monkeypatch):
    monkeypatch.setattr(settings, "CRON_SECRET", "s3cret-value")


# ── public reads ────────────────────────────────────────────────────────────


async def test_public_get_serves_auto_and_approved_with_cache_headers(client: AsyncClient, db_session):
    db_session.add_all([block("a"), block("b", "approved"), block("c", "needs_review"), block("d", "failed")])
    await db_session.flush()
    ok = await client.get("/api/v1/content/locality/a")
    assert ok.status_code == 200
    data = ok.json()
    assert data["slug"] == "a" and data["locale"] == "en" and data["indexable"] is True
    assert "errors" not in data and "review_status" not in data
    assert "s-maxage=3600" in ok.headers["cache-control"] and "public" in ok.headers["cache-control"]
    assert (await client.get("/api/v1/content/locality/b")).status_code == 200
    for hidden in ("c", "d", "missing"):
        assert (await client.get(f"/api/v1/content/locality/{hidden}")).status_code == 404


async def test_public_get_locale_and_validation(client: AsyncClient, db_session):
    db_session.add(block("a", locale="hi"))
    await db_session.flush()
    assert (await client.get("/api/v1/content/locality/a")).status_code == 404
    assert (await client.get("/api/v1/content/locality/a?locale=hi")).status_code == 200
    assert (await client.get("/api/v1/content/locality/a?locale=fr")).status_code == 422
    assert (await client.get("/api/v1/content/city/a")).status_code == 422
    assert (await client.get("/api/v1/content/locality/a?bogus=1")).status_code == 422


async def test_manifest_lists_only_served_rows(client: AsyncClient, db_session):
    db_session.add_all(
        [block("a"), block("a", locale="hi"), block("b", "needs_review"), block("9", entity_type="property",
                                                                               indexable=False)]
    )
    await db_session.flush()
    resp = await client.get("/api/v1/content/manifest")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [(i["entity_type"], i["slug"], i["locale"], i["indexable"]) for i in items] == [
        ("locality", "a", "en", True), ("locality", "a", "hi", True), ("property", "9", "en", False),
    ]
    assert "s-maxage" in resp.headers["cache-control"]
    only = await client.get("/api/v1/content/manifest?entity_type=property")
    assert [i["slug"] for i in only.json()["items"]] == ["9"]


# ── cron run ────────────────────────────────────────────────────────────────


async def test_run_without_configured_secret_is_503(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "CRON_SECRET", None)
    resp = await client.post("/api/v1/admin/content/run", json={}, headers=CRON)
    assert resp.status_code == 503


@pytest.mark.parametrize("headers", [{}, {"X-Cron-Secret": "wrong"}, {"X-Cron-Secret": ""}])
async def test_run_rejects_missing_or_wrong_secret(client: AsyncClient, cron_secret, headers):
    resp = await client.post("/api/v1/admin/content/run", json={}, headers=headers)
    assert resp.status_code == 403


async def test_run_rejects_user_jwt_without_secret(authenticated_client: AsyncClient, cron_secret):
    resp = await authenticated_client.post("/api/v1/admin/content/run", json={})
    assert resp.status_code == 403


async def test_run_generates_and_is_idempotent(client: AsyncClient, cron_secret, sector_data, db_session, monkeypatch):
    from app.models.content import Locality
    from app.services.content import facts

    sheet = await facts.build_locality_sheet(db_session, await db_session.get(Locality, "sector-56"))
    provider = FakeProvider([compose(sheet)])
    monkeypatch.setattr("app.api.api_v1.endpoints.admin_content.make_provider", lambda: provider)
    monkeypatch.setattr(settings, "CONTENT_MIN_CALL_INTERVAL_S", 0)
    payload = {"entity_type": "locality", "locales": ["en"], "slugs": ["sector-56"]}
    first = await client.post("/api/v1/admin/content/run", json=payload, headers=CRON)
    assert first.status_code == 200, first.text
    assert first.json()["generated"] == 1 and first.json()["done"] is True
    second = await client.post("/api/v1/admin/content/run", json=payload, headers=CRON)
    assert second.json()["generated"] == 0 and second.json()["skipped"] == 1 and second.json()["calls"] == 0
    assert len(provider.calls) == 1
    served = await client.get("/api/v1/content/locality/sector-56")
    assert served.status_code == 200 and served.json()["indexable"] is True


async def test_run_without_ai_key_is_503(client: AsyncClient, cron_secret, monkeypatch):
    monkeypatch.setattr(settings, "AGNES_AI_API_KEY", None)
    resp = await client.post("/api/v1/admin/content/run", json={}, headers=CRON)
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "AI_NOT_CONFIGURED"


async def test_run_validates_body(client: AsyncClient, cron_secret):
    for bad in ({"max_entities": 500}, {"locales": ["fr"]}, {"entity_type": "city"}, {"extra": 1}):
        resp = await client.post("/api/v1/admin/content/run", json=bad, headers=CRON)
        assert resp.status_code == 422, bad


# ── admin review ────────────────────────────────────────────────────────────


async def test_review_list_requires_admin(authenticated_client: AsyncClient, client: AsyncClient):
    assert (await authenticated_client.get("/api/v1/admin/content/review")).status_code == 403
    assert (await client.get("/api/v1/admin/content/review")).status_code in (401, 403)


async def test_review_list_filters_and_pages(admin_authenticated_client: AsyncClient, db_session):
    db_session.add_all([block(f"s{i}", "needs_review") for i in range(3)] + [block("ok")])
    await db_session.flush()
    resp = await admin_authenticated_client.get("/api/v1/admin/content/review?review_status=needs_review&limit=2")
    assert resp.status_code == 200
    page = resp.json()
    assert len(page["items"]) == 2 and page["has_more"] is True
    assert "errors" in page["items"][0] and page["items"][0]["review_status"] == "needs_review"
    nxt = await admin_authenticated_client.get(
        f"/api/v1/admin/content/review?review_status=needs_review&limit=2&cursor={page['next_cursor']}"
    )
    assert len(nxt.json()["items"]) == 1 and nxt.json()["has_more"] is False
    mismatch = await admin_authenticated_client.get(
        f"/api/v1/admin/content/review?review_status=failed&cursor={page['next_cursor']}"
    )
    assert mismatch.status_code == 422
    bad = await admin_authenticated_client.get("/api/v1/admin/content/review?review_status=nope")
    assert bad.status_code == 422


async def test_status_update_rules(admin_authenticated_client: AsyncClient, authenticated_client, db_session):
    rich = block("rich", "needs_review", indexable=False)
    thin = block("thin", "needs_review", indexable=False, fact_count=3)
    failed = block("bad", "failed", indexable=False)
    db_session.add_all([rich, thin, failed])
    await db_session.flush()

    ok = await admin_authenticated_client.patch(f"/api/v1/admin/content/{rich.id}/status",
                                                json={"review_status": "approved"})
    assert ok.status_code == 200 and ok.json()["review_status"] == "approved" and ok.json()["indexable"] is True
    noindex = await admin_authenticated_client.patch(f"/api/v1/admin/content/{thin.id}/status",
                                                     json={"review_status": "approved"})
    assert noindex.json()["review_status"] == "approved" and noindex.json()["indexable"] is False
    conflict = await admin_authenticated_client.patch(f"/api/v1/admin/content/{failed.id}/status",
                                                      json={"review_status": "approved"})
    assert conflict.status_code == 409
    rejected = await admin_authenticated_client.patch(f"/api/v1/admin/content/{rich.id}/status",
                                                      json={"review_status": "rejected"})
    assert rejected.json()["indexable"] is False
    assert (await admin_authenticated_client.patch("/api/v1/admin/content/999999/status",
                                                   json={"review_status": "approved"})).status_code == 404
    assert (await admin_authenticated_client.patch(f"/api/v1/admin/content/{rich.id}/status",
                                                   json={"review_status": "failed"})).status_code == 422
    stored = (await db_session.execute(select(ContentBlock.review_status).where(ContentBlock.id == rich.id))).scalar_one()
    assert stored == "rejected" and runner.PROMPT_VERSION


# ── market digest and the property write trigger ────────────────────────────


async def test_market_digest_needs_the_cron_secret(client: AsyncClient, cron_secret):
    assert (await client.post("/api/v1/admin/content/market-digest")).status_code == 403
    wrong = await client.post("/api/v1/admin/content/market-digest", headers={"X-Cron-Secret": "nope"})
    assert wrong.status_code == 403


async def test_market_digest_skips_when_quiet(client: AsyncClient, cron_secret, monkeypatch, test_admin_user):
    monkeypatch.setattr("app.api.api_v1.endpoints.admin_content.make_provider", lambda: FakeProvider([{}]))
    monkeypatch.setattr(settings, "AUTO_BLOG_PUBLISHER_USER_ID", test_admin_user.id)
    resp = await client.post("/api/v1/admin/content/market-digest", headers=CRON)
    assert resp.status_code == 200 and resp.json()["status"] == "skipped" and resp.json()["changes"] == 0


async def test_property_create_and_update_trigger_content_task(authenticated_client: AsyncClient, monkeypatch):
    from unittest.mock import AsyncMock

    task = AsyncMock()
    monkeypatch.setattr("app.api.api_v1.endpoints.properties.generate_property_content", task)
    body = {"title": "Flat in Sector 85", "property_type": "apartment", "purpose": "buy",
            "base_price": 8500000, "city": "Gurugram", "locality": "Sector 85"}
    created = await authenticated_client.post("/api/v1/properties", json=body)
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    task.assert_awaited_once_with(pid)
    updated = await authenticated_client.put(f"/api/v1/properties/{pid}", json={"base_price": 9000000})
    assert updated.status_code == 200, updated.text
    assert task.await_count == 2
