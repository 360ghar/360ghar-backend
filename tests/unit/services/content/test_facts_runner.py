"""Fact sheets from the database and the batch runner with a mocked provider."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.content import ContentBlock, Locality
from app.services.ai.base import AIProviderError
from app.services.content import facts, runner
from tests.unit.services.content.conftest import FakeProvider, compose

pytestmark = pytest.mark.asyncio


async def build(db):
    loc = await db.get(Locality, "sector-56")
    return await facts.build_locality_sheet(db, loc)


async def test_locality_sheet_has_sourced_facts_and_passes_threshold(db_session, sector_data):
    sheet = await build(db_session)
    keys = {f.key for f in sheet.facts}
    assert {"place", "landmark_1", "median_sale", "price_sale", "circle_rate", "rera_count", "rera_projects"} <= keys
    assert all(f.source and f.display for f in sheet.facts)
    shown = {f.key: f.display for f in sheet.facts}
    assert shown["median_sale"] == "₹1.25 crore"
    assert shown["circle_rate"] == "₹45,000 per sq yd"
    assert "Skyline Heights" in sheet.allowed_names()
    assert sheet.meets_threshold


async def test_sheet_below_threshold_is_noindex(db_session):
    db_session.add(Locality(slug="tiny", name="Tiny", city="Gurugram", place_type="locality"))
    await db_session.flush()
    sheet = await facts.build_locality_sheet(db_session, await db_session.get(Locality, "tiny"))
    assert not sheet.meets_threshold


async def test_run_generates_then_skips_when_facts_unchanged(db_session, sector_data):
    sheet = await build(db_session)
    provider = FakeProvider([compose(sheet)])
    stats = await runner.run_batch(db_session, provider, entity_type="locality", locales=["en"])
    assert (stats.generated, stats.calls, stats.done) == (1, 1, True)
    row = (await db_session.execute(select(ContentBlock))).scalar_one()
    assert row.review_status == "auto" and row.indexable and row.key_fact
    assert row.facts_hash == sheet.facts_hash() and row.fact_count == sheet.fact_count

    again = await runner.run_batch(db_session, provider, entity_type="locality", locales=["en"])
    assert (again.generated, again.skipped, again.calls) == (0, 1, 0)
    assert len(provider.calls) == 1


async def test_changed_facts_regenerate(db_session, sector_data):
    sheet = await build(db_session)
    provider = FakeProvider([compose(sheet)])
    await runner.run_batch(db_session, provider, entity_type="locality", locales=["en"])
    loc = await db_session.get(Locality, "sector-56")
    loc.landmarks = []
    await db_session.flush()
    sheet2 = await build(db_session)
    provider2 = FakeProvider([compose(sheet2)])
    stats = await runner.run_batch(db_session, provider2, entity_type="locality", locales=["en"])
    assert stats.generated == 1 and len(provider2.calls) == 1


async def test_validator_errors_are_fed_back_then_succeed(db_session, sector_data):
    sheet = await build(db_session)
    bad = compose(sheet, highlights=["Median listed price is ₹9.99 crore", "b", "c"])
    provider = FakeProvider([bad, compose(sheet)])
    stats = await runner.run_batch(db_session, provider, entity_type="locality", locales=["en"])
    assert stats.calls == 2 and stats.generated == 1
    feedback = provider.calls[1][-1].content
    assert "9.99 crore" in feedback and "failed these checks" in feedback


async def test_three_failures_mark_failed_and_are_not_retried(db_session, sector_data):
    sheet = await build(db_session)
    bad = compose(sheet, highlights=["Guaranteed returns", "b", "c"])
    provider = FakeProvider([bad])
    stats = await runner.run_batch(db_session, provider, entity_type="locality", locales=["en"])
    assert (stats.failed, stats.calls) == (1, 3)
    row = (await db_session.execute(select(ContentBlock))).scalar_one()
    assert row.review_status == "failed" and not row.indexable and row.errors
    again = await runner.run_batch(db_session, provider, entity_type="locality", locales=["en"])
    assert again.skipped == 1 and again.calls == 0
    retried = await runner.run_batch(
        db_session, FakeProvider([compose(sheet)]), entity_type="locality", locales=["en"], retry_failed=True
    )
    assert retried.generated == 1


async def test_duplicate_of_sibling_is_rejected_and_similar_goes_to_review(db_session, sector_data):
    sheet = await build(db_session)
    out = compose(sheet)
    db_session.add(ContentBlock(entity_type="locality", slug="other", locale="en", body=out, facts_hash="x",
                                prompt_version=runner.PROMPT_VERSION, review_status="auto"))
    await db_session.flush()
    stats = await runner.run_batch(db_session, FakeProvider([out]), entity_type="locality", locales=["en"],
                                   slugs=["sector-56"])
    assert stats.rejected == 1
    row = (await db_session.execute(select(ContentBlock).where(ContentBlock.slug == "sector-56"))).scalar_one()
    assert row.review_status == "rejected" and not row.indexable and row.dup_score >= 0.5


async def test_quota_error_stops_run_without_writing(db_session, sector_data):
    err = AIProviderError("usage limit reached", provider="Agnes AI", status_code=429)
    stats = await runner.run_batch(db_session, FakeProvider([err]), entity_type="locality", locales=["en", "hi"])
    assert stats.stopped_reason == "rate_limited" and stats.generated == 0
    assert (await db_session.execute(select(ContentBlock))).first() is None
    assert not stats.done


async def test_entity_limit_sets_cursor_for_resume(db_session, sector_data):
    db_session.add(Locality(slug="sector-57", name="Sector 57", city="Gurugram", place_type="sector"))
    await db_session.flush()
    sheet = await build(db_session)
    provider = FakeProvider([compose(sheet)])
    stats = await runner.run_batch(db_session, provider, entity_type="locality", locales=["en"], max_entities=1,
                                   city="Gurugram")
    # sector-56 has facts for compose(); sector-57 has none and would fail validation, so stop after one.
    assert stats.stopped_reason == "entity_limit" and stats.next_after == "sector-56" and not stats.done


async def test_sheet_failed_status_never_indexable_and_hi_locale_separate_rows(db_session, sector_data):
    sheet = await build(db_session)
    provider = FakeProvider([compose(sheet)])
    await runner.run_batch(db_session, provider, entity_type="locality", locales=["en", "hi"], slugs=["sector-56"])
    rows = (await db_session.execute(select(ContentBlock.locale))).scalars().all()
    assert sorted(rows) == ["en", "hi"]
