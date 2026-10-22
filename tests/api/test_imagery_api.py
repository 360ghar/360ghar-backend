"""Imagery: house-style key, art generation, the OG redirect and the cron run."""

from __future__ import annotations

import base64
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from urllib.parse import unquote

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models.content import GeneratedImage, Locality
from app.services.ai.image_gen.schemas import ImageGenResponse
from app.services.ai.imagery import service, style
from tests.fixtures.factories import PropertyFactory

pytestmark = pytest.mark.asyncio

CRON = {"X-Cron-Secret": "s3cret-value"}
PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG fake").decode()
GEN = "app.services.ai.image_gen.service.generate_image"
UPLOAD = "app.services.ai.imagery.service._upload"


@pytest.fixture(autouse=True)
def _cloud(monkeypatch):
    monkeypatch.setattr(settings, "CRON_SECRET", "s3cret-value")
    monkeypatch.setattr(settings, "CLOUDINARY_CLOUD_NAME", "democloud")
    monkeypatch.setattr(settings, "CLOUDINARY_API_KEY", "k")
    monkeypatch.setattr(settings, "CLOUDINARY_API_SECRET", "s")


def ok_upload(png, subject, key):
    return {"public_id": f"360ghar/generated/art/{subject.subject_type}/{subject.slug}", "secure_url": "https://x/y.png"}


# ── style and key ───────────────────────────────────────────────────────────


def test_key_is_stable_and_depends_on_every_input():
    k = style.image_key("locality", "sector-49", "16:9", "1K")
    assert k == style.image_key("locality", "sector-49", "16:9", "1K") and len(k) == 64
    for other in (
        style.image_key("city", "sector-49", "16:9", "1K"),
        style.image_key("locality", "sector-50", "16:9", "1K"),
        style.image_key("locality", "sector-49", "1:1", "1K"),
        style.image_key("locality", "sector-49", "16:9", "2K"),
    ):
        assert other != k


def test_key_changes_with_style_version(monkeypatch):
    before = style.image_key("city", "gurugram", "16:9", "1K")
    monkeypatch.setattr(style, "STYLE_VERSION", "v2")
    assert style.image_key("city", "gurugram", "16:9", "1K") != before


def test_prompt_is_the_scene_and_the_style_is_the_instruction():
    prompt = style.build_prompt("locality", "Sector 49", "Gurugram")
    assert "Sector 49" in prompt and "Gurugram" in prompt and style.HOUSE_STYLE not in prompt
    for banned in ("No text", "no logos", "no faces"):
        assert banned in style.HOUSE_STYLE


def test_compose_og_url_escapes_text_and_lays_layers():
    url = service.compose_og_url("360ghar/generated/art/city/x", "3 BHK, Sector 49 / Gurugram", price="₹1.20 crore", locality="Sector 49")
    decoded = unquote(url)
    assert "democloud" in url and "w_1200" in url and "h_630" in url
    assert "3 BHK" in decoded and "1.20 crore" in decoded
    # a comma or slash in the title must not split the layer
    assert url.count("l_text:Georgia_60_bold:") == 1
    assert "%252C" in url or "%2C" in url


# ── ensure_art ──────────────────────────────────────────────────────────────


async def test_ensure_art_is_idempotent(db_session):
    subject = service.Subject("city", "gurugram", "Gurugram")
    with patch(GEN, new_callable=AsyncMock, return_value=ImageGenResponse(success=True, image=PNG)) as gen, patch(UPLOAD, side_effect=ok_upload):
        assert (await service.ensure_art(db_session, subject))[0] == "ready"
        assert (await service.ensure_art(db_session, subject))[0] == "skipped"
    assert gen.await_count == 1
    row = (await db_session.execute(select(GeneratedImage))).scalar_one()
    assert row.status == "ready" and row.key == style.image_key("city", "gurugram", "16:9", "1K")
    assert row.public_id.endswith("city/gurugram")


async def test_ensure_art_quota_sets_retry_and_blocks_until_due(db_session):
    subject = service.Subject("city", "gurugram", "Gurugram")
    bad = ImageGenResponse(success=False, error="x", code="QUOTA_EXCEEDED")
    with patch(GEN, new_callable=AsyncMock, return_value=bad) as gen:
        status, retry = await service.ensure_art(db_session, subject)
        again = await service.ensure_art(db_session, subject)
    assert (status, retry) == ("rate_limited", 1800) and again[0] == "skipped" and gen.await_count == 1
    row = (await db_session.execute(select(GeneratedImage))).scalar_one()
    assert row.status == "failed" and row.retry_after is not None


async def test_ensure_art_retries_after_due_date(db_session):
    subject = service.Subject("city", "gurugram", "Gurugram")
    with patch(GEN, new_callable=AsyncMock, return_value=ImageGenResponse(success=False, error="x", code="GENERATION_FAILED")):
        assert (await service.ensure_art(db_session, subject))[0] == "failed"
    row = (await db_session.execute(select(GeneratedImage))).scalar_one()
    from datetime import timedelta

    row.retry_after = service.utc_now() - timedelta(minutes=1)
    await db_session.flush()
    with patch(GEN, new_callable=AsyncMock, return_value=ImageGenResponse(success=True, image=PNG)), patch(UPLOAD, side_effect=ok_upload):
        assert (await service.ensure_art(db_session, subject))[0] == "ready"


async def test_upload_failure_keeps_row_retryable(db_session):
    subject = service.Subject("blog", "post-1", "A post")
    with patch(GEN, new_callable=AsyncMock, return_value=ImageGenResponse(success=True, image=PNG)), patch(UPLOAD, side_effect=RuntimeError("boom")):
        assert (await service.ensure_art(db_session, subject))[0] == "failed"
    row = (await db_session.execute(select(GeneratedImage))).scalar_one()
    assert row.status == "failed" and row.url is None


# ── OG endpoint ─────────────────────────────────────────────────────────────


async def test_og_unknown_subject_404_and_bad_kind_422(client: AsyncClient):
    assert (await client.get("/api/v1/og/locality/nope", follow_redirects=False)).status_code == 404
    assert (await client.get("/api/v1/og/property/abc", follow_redirects=False)).status_code == 404
    assert (await client.get("/api/v1/og/user/1", follow_redirects=False)).status_code == 422


async def test_og_without_art_redirects_to_brand_fallback(client: AsyncClient, db_session):
    db_session.add(Locality(slug="sector-49", name="Sector 49", city="Gurugram", place_type="sector"))
    await db_session.flush()
    resp = await client.get("/api/v1/og/locality/sector-49", follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"] == settings.OG_FALLBACK_IMAGE_URL
    assert "max-age=60" in resp.headers["cache-control"]


async def test_og_with_art_redirects_to_composed_card(client: AsyncClient, db_session):
    db_session.add(Locality(slug="sector-49", name="Sector 49", city="Gurugram", place_type="sector"))
    db_session.add(GeneratedImage(key=style.image_key("locality", "sector-49", "16:9", "1K"), subject_type="locality",
                                  subject_slug="sector-49", public_id="360ghar/generated/art/locality/sector-49-abc",
                                  url="https://x", status="ready"))
    await db_session.flush()
    resp = await client.get("/api/v1/og/locality/sector-49", follow_redirects=False)
    loc = resp.headers["location"]
    assert resp.status_code == 302 and loc.startswith("https://res.cloudinary.com/democloud/")
    assert "Sector%2049" in loc or "Sector 49" in unquote(loc)
    assert "s-maxage=3600" in resp.headers["cache-control"]


async def test_og_property_shows_exact_price_and_locality(client: AsyncClient, db_session, test_user):
    prop = await PropertyFactory.create(db_session, owner=test_user, title="Sunny 3BHK", base_price=Decimal("12000000"),
                                        purpose=__import__("app.models.enums", fromlist=["PropertyPurpose"]).PropertyPurpose.buy)
    db_session.add(GeneratedImage(key=style.image_key("property", str(prop.id), "16:9", "1K"), subject_type="property",
                                  subject_slug=str(prop.id), public_id="360ghar/generated/art/property/x", url="u", status="ready"))
    await db_session.flush()
    resp = await client.get(f"/api/v1/og/property/{prop.id}", follow_redirects=False)
    text = unquote(unquote(resp.headers["location"]))
    assert "Sunny 3BHK" in text and "1.20 crore" in text and "Andheri, Mumbai" in text


async def test_og_post_alias_serves_blog(client: AsyncClient):
    assert (await client.get("/api/v1/og/post/none", follow_redirects=False)).status_code == 404


async def test_og_compose_failure_falls_back_not_500(client: AsyncClient, db_session):
    db_session.add(Locality(slug="a", name="A", city="C", place_type="sector"))
    db_session.add(GeneratedImage(key=style.image_key("locality", "a", "16:9", "1K"), subject_type="locality",
                                  subject_slug="a", public_id="p", url="u", status="ready"))
    await db_session.flush()
    with patch.object(service, "compose_og_url", side_effect=RuntimeError("no creds")):
        resp = await client.get("/api/v1/og/locality/a", follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"] == settings.OG_FALLBACK_IMAGE_URL


# ── cron run ────────────────────────────────────────────────────────────────


async def test_run_requires_cron_secret(client: AsyncClient, monkeypatch):
    assert (await client.post("/api/v1/admin/imagery/run", json={})).status_code == 403
    assert (await client.post("/api/v1/admin/imagery/run", json={}, headers={"X-Cron-Secret": "bad"})).status_code == 403
    monkeypatch.setattr(settings, "CRON_SECRET", None)
    assert (await client.post("/api/v1/admin/imagery/run", json={}, headers=CRON)).status_code == 503


async def test_run_validates_body(client: AsyncClient):
    for body in ({"max_items": 0}, {"max_items": 21}, {"kinds": ["user"]}, {"variant": "x"}, {"bogus": 1}):
        assert (await client.post("/api/v1/admin/imagery/run", json=body, headers=CRON)).status_code == 422


async def test_run_generates_then_skips(client: AsyncClient, db_session):
    db_session.add_all([Locality(slug=f"s{i}", name=f"S{i}", city="Gurugram", place_type="sector") for i in range(3)])
    await db_session.flush()
    with patch(GEN, new_callable=AsyncMock, return_value=ImageGenResponse(success=True, image=PNG)) as gen, patch(UPLOAD, side_effect=ok_upload):
        first = await client.post("/api/v1/admin/imagery/run", json={"kinds": ["city"], "max_items": 5}, headers=CRON)
        second = await client.post("/api/v1/admin/imagery/run", json={"kinds": ["city"], "max_items": 5}, headers=CRON)
    assert first.status_code == 200 and first.json()["generated"] == 1 and first.json()["done"] is True
    assert second.json()["generated"] == 0 and gen.await_count == 1


async def test_run_hero_variant_uses_2k(client: AsyncClient, db_session):
    db_session.add(Locality(slug="s", name="S", city="Gurugram", place_type="sector"))
    await db_session.flush()
    with patch(GEN, new_callable=AsyncMock, return_value=ImageGenResponse(success=True, image=PNG)) as gen, patch(UPLOAD, side_effect=ok_upload):
        await client.post("/api/v1/admin/imagery/run", json={"kinds": ["city"], "variant": "hero"}, headers=CRON)
    assert gen.await_args.kwargs["size"] == "2K"


async def test_run_rate_limited_returns_429_with_retry_after(client: AsyncClient, db_session):
    db_session.add_all([Locality(slug="a", name="A", city="Gurugram", place_type="sector"),
                        Locality(slug="b", name="B", city="Noida", place_type="sector")])
    await db_session.flush()
    bad = ImageGenResponse(success=False, error="x", code="QUOTA_EXCEEDED")
    with patch(GEN, new_callable=AsyncMock, return_value=bad):
        resp = await client.post("/api/v1/admin/imagery/run", json={"kinds": ["city"]}, headers=CRON)
    assert resp.status_code == 429 and resp.headers["retry-after"] == "1800"
    assert resp.json()["retry_after"] == 1800 and resp.json()["stopped_reason"] == "rate_limited"


async def test_run_limits_concurrency_to_four(client: AsyncClient, db_session):
    import asyncio

    db_session.add_all([Locality(slug=f"s{i}", name=f"S{i}", city=f"City{i}", place_type="sector") for i in range(10)])
    await db_session.flush()
    live = peak = 0

    async def slow(*a, **k):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.02)
        live -= 1
        return ImageGenResponse(success=True, image=PNG)

    with patch(GEN, side_effect=slow), patch(UPLOAD, side_effect=ok_upload):
        resp = await client.post("/api/v1/admin/imagery/run", json={"kinds": ["city"], "max_items": 10}, headers=CRON)
    assert resp.json()["generated"] == 10 and 1 < peak <= 4


# ── review follow-ups ───────────────────────────────────────────────────────


async def test_og_post_alias_serves_a_published_post(client: AsyncClient, db_session):
    from app.models.blogs import BlogPost

    db_session.add(BlogPost(title="Why Sector 49", slug="why-sector-49", content="x", status="published"))
    db_session.add(GeneratedImage(key=style.image_key("blog", "why-sector-49", "16:9", "1K"), subject_type="blog",
                                  subject_slug="why-sector-49", public_id="p", url="u", status="ready"))
    await db_session.flush()
    with patch(GEN, new_callable=AsyncMock) as gen:
        resp = await client.get("/api/v1/og/post/why-sector-49", follow_redirects=False)
    assert resp.status_code == 302 and "Why%20Sector%2049" in resp.headers["location"]
    assert gen.await_count == 0, "a card request never calls the model"


async def test_og_hides_non_live_flatmate_listing_and_odd_digits(client: AsyncClient, db_session, test_user):
    from app.models.enums import PropertyType

    pg = await PropertyFactory.create(db_session, owner=test_user, property_type=PropertyType.pg,
                                      listing_preferences={"moderation_status": "paused"})
    live = await PropertyFactory.create(db_session, owner=test_user, property_type=PropertyType.pg,
                                        listing_preferences={"moderation_status": "live"})
    assert (await client.get(f"/api/v1/og/property/{pg.id}", follow_redirects=False)).status_code == 404
    assert (await client.get(f"/api/v1/og/property/{live.id}", follow_redirects=False)).status_code == 302
    assert (await client.get("/api/v1/og/property/%C2%B2", follow_redirects=False)).status_code == 404


async def test_og_price_follows_purpose(client: AsyncClient, db_session, test_user):
    from app.models.enums import PropertyPurpose

    prop = await PropertyFactory.create(db_session, owner=test_user, purpose=PropertyPurpose.rent, base_price=Decimal("9000000"))
    prop.monthly_rent = None
    db_session.add(GeneratedImage(key=style.image_key("property", str(prop.id), "16:9", "1K"), subject_type="property",
                                  subject_slug=str(prop.id), public_id="p", url="u", status="ready"))
    await db_session.flush()
    title, price, _ = await service.card_text(db_session, "property", str(prop.id))
    assert price is None, "a rental without a monthly rent must not show the sale price"


async def test_run_rejects_repeated_kinds(client: AsyncClient):
    resp = await client.post("/api/v1/admin/imagery/run", json={"kinds": ["city", "city"]}, headers=CRON)
    assert resp.status_code == 422


async def test_claim_is_taken_once(db_session):
    subject = service.Subject("city", "gurugram", "Gurugram")
    key = style.image_key("city", "gurugram", "16:9", "1K")
    assert await service._claim(db_session, key, subject) is True
    assert await service._claim(db_session, key, subject) is False  # fresh pending row
    from datetime import timedelta

    row = await service.get_row(db_session, key)
    row.updated_at = service.utc_now() - timedelta(hours=1)
    await db_session.flush()
    assert await service._claim(db_session, key, subject) is True  # stale pending is taken over
    row.status = "ready"
    await db_session.flush()
    assert await service._claim(db_session, key, subject) is False  # ready is never taken


async def test_pending_subjects_pages_past_the_first_page(db_session, monkeypatch):
    monkeypatch.setattr(service, "PAGE", 2)
    db_session.add_all([Locality(slug=f"c{i}", name=f"C{i}", city=f"City {i}", place_type="sector") for i in range(5)])
    await db_session.flush()
    for slug in ("city-0", "city-1", "city-2"):
        db_session.add(GeneratedImage(key=style.image_key("city", slug, "16:9", "1K"), subject_type="city",
                                      subject_slug=slug, public_id="p", url="u", status="ready"))
    await db_session.flush()
    todo = await service.pending_subjects(db_session, ["city"], 10)
    assert [s.slug for s in todo] == ["city-3", "city-4"]


async def test_cities_come_from_listings_too(db_session, test_user):
    await PropertyFactory.create(db_session, owner=test_user, city="Pune")
    names = {s.name for s in await service.list_subjects(db_session, "city", 50)}
    assert "Pune" in names


async def test_rate_limit_stops_the_rest_of_the_batch(client: AsyncClient, db_session):
    db_session.add_all([Locality(slug=f"s{i}", name=f"S{i}", city=f"City{i}", place_type="sector") for i in range(8)])
    await db_session.flush()
    bad = ImageGenResponse(success=False, error="x", code="QUOTA_EXCEEDED")
    with patch(GEN, new_callable=AsyncMock, return_value=bad) as gen:
        resp = await client.post("/api/v1/admin/imagery/run", json={"kinds": ["city"], "max_items": 8}, headers=CRON)
    assert resp.status_code == 429
    assert gen.await_count <= service.CONCURRENCY, "no new image starts once the provider said 429"
