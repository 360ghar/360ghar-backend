from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.blogs import BlogPost
from app.schemas.blog import BlogPostCreate
from app.services.blog import create_blog_post
from app.services.blog_auto_publish import (
    DailyPerplexityBlogPublisher,
    DiscoveredNewsItem,
    GeneratedBlogDraft,
    RecentPublishedPost,
)


class _DummyBeginContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _DummySessionContext:
    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _DummyManagedSession:
    def __init__(self) -> None:
        self.begin_calls = 0

    def begin(self) -> _DummyBeginContext:
        self.begin_calls += 1
        return _DummyBeginContext()


class TestDailyPerplexityBlogPublisher:
    def test_build_discovery_prompt_includes_recent_posts(self) -> None:
        publisher = DailyPerplexityBlogPublisher()
        prompt = publisher._build_discovery_prompt(
            recent_posts=[
                RecentPublishedPost(
                    title="DLF launches a new Gurugram tower",
                    slug="dlf-launches-a-new-gurugram-tower",
                    excerpt="Existing article excerpt",
                )
            ],
            today_label="03/12/2026",
            max_items=3,
        )

        assert "03/12/2026" in prompt
        assert "DLF launches a new Gurugram tower" in prompt
        assert "Existing article excerpt" in prompt

    def test_filter_discovered_items_rejects_invalid_candidates(self) -> None:
        publisher = DailyPerplexityBlogPublisher()
        today = publisher._today_ist()
        today_label = publisher._format_perplexity_date(today)
        recent_posts = [
            RecentPublishedPost(
                title="Dwarka Expressway demand jumps in Gurugram",
                slug="dwarka-expressway-demand-jumps",
                source_urls=["https://example.com/existing-story"],
            )
        ]

        filtered = publisher._filter_discovered_items(
            items=[
                DiscoveredNewsItem(
                    title="Dwarka Expressway demand jumps in Gurugram",
                    summary="Duplicate title and source should be dropped",
                    source_name="Example",
                    source_url="https://example.com/existing-story",
                    publication_date=today_label,
                    why_new="It is new today.",
                    citations=["https://example.com/existing-story"],
                    tags=["Expressway"],
                ),
                DiscoveredNewsItem(
                    title="Fresh Gurugram housing update",
                    summary="Missing citations should be dropped",
                    source_name="Example",
                    source_url="https://example.com/new-story",
                    publication_date=today_label,
                    why_new="It is new today.",
                    citations=[],
                    tags=["Housing"],
                ),
                DiscoveredNewsItem(
                    title="Old Gurugram housing update",
                    summary="Old dates should be dropped",
                    source_name="Example",
                    source_url="https://example.com/old-story",
                    publication_date="03/11/2026",
                    why_new="It is new today.",
                    citations=["https://example.com/old-story"],
                    tags=["Housing"],
                ),
                DiscoveredNewsItem(
                    title="Instagram rumor on Gurugram towers",
                    summary="Blocked domains should be dropped",
                    source_name="Instagram",
                    source_url="https://instagram.com/story",
                    publication_date=today_label,
                    why_new="It is new today.",
                    citations=["https://instagram.com/story"],
                    tags=["Rumor"],
                ),
                DiscoveredNewsItem(
                    title="Haryana updates new stamp duty guidance",
                    summary="This is valid and should survive filtering",
                    source_name="The Hindu BusinessLine",
                    source_url="https://www.thehindubusinessline.com/markets/new-stamp-duty-guidance",
                    publication_date=today_label,
                    why_new="It is a new same-day policy update.",
                    citations=["https://www.thehindubusinessline.com/markets/new-stamp-duty-guidance"],
                    tags=["Policy", "Stamp Duty"],
                ),
            ],
            recent_posts=recent_posts,
            today=today,
        )

        assert len(filtered) == 1
        assert filtered[0].title == "Haryana updates new stamp duty guidance"

    @pytest.mark.asyncio
    async def test_publish_daily_posts_creates_active_blog_post(
        self,
        db_session,
        monkeypatch: pytest.MonkeyPatch,
        test_admin_user,
    ) -> None:
        monkeypatch.setattr(settings, "PERPLEXITY_API_KEY", "test-key")
        monkeypatch.setattr(settings, "AUTO_BLOG_PUBLISHER_USER_ID", test_admin_user.id)
        monkeypatch.setattr(settings, "AUTO_BLOG_MAX_POSTS_PER_RUN", 3)

        publisher = DailyPerplexityBlogPublisher()
        today_label = publisher._format_perplexity_date(publisher._today_ist())
        discovered_item = DiscoveredNewsItem(
            title="Gurugram rental values rise near major metro corridor",
            summary="Fresh market coverage on a same-day Gurugram rental move.",
            source_name="Economic Times",
            source_url="https://economictimes.indiatimes.com/gurugram-rentals",
            publication_date=today_label,
            why_new="The report was published today and focuses on Gurugram.",
            citations=["https://economictimes.indiatimes.com/gurugram-rentals"],
            tags=["Rent", "Metro"],
        )
        generated_draft = GeneratedBlogDraft(
            title="Gurugram rentals climb near metro-linked corridors",
            excerpt="Rental values have moved up near metro-linked micro-markets in Gurugram.",
            content_html=(
                "<p>Rental values are rising in select Gurugram markets, especially in corridors "
                "linked to new metro-led demand and stronger leasing activity.</p>"
            ),
            tags=["Rent", "Gurugram"],
            citations=["https://economictimes.indiatimes.com/gurugram-rentals"],
        )

        monkeypatch.setattr(publisher, "_discover_stories", AsyncMock(return_value=[discovered_item]))
        monkeypatch.setattr(publisher, "_generate_blog_draft", AsyncMock(return_value=generated_draft))

        stats = await publisher.publish_daily_posts(db_session)

        assert stats["published_count"] == 1
        result = await db_session.execute(
            select(BlogPost).where(BlogPost.title == "Gurugram rentals climb near metro-linked corridors")
        )
        post = result.scalar_one()
        assert post.active is True
        assert "Sources" in post.content
        assert "economictimes.indiatimes.com" in post.content

    @pytest.mark.asyncio
    async def test_publish_daily_posts_skips_missing_or_non_admin_publisher(
        self,
        db_session,
        monkeypatch: pytest.MonkeyPatch,
        test_user,
    ) -> None:
        monkeypatch.setattr(settings, "PERPLEXITY_API_KEY", "test-key")
        monkeypatch.setattr(settings, "AUTO_BLOG_PUBLISHER_USER_ID", test_user.id)

        publisher = DailyPerplexityBlogPublisher()
        discover_mock = AsyncMock()
        monkeypatch.setattr(publisher, "_discover_stories", discover_mock)

        stats = await publisher.publish_daily_posts(db_session)

        assert stats["published_count"] == 0
        assert stats["skipped_count"] == 1
        discover_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_publish_daily_posts_skips_when_another_worker_holds_lock(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "PERPLEXITY_API_KEY", "test-key")

        publisher = DailyPerplexityBlogPublisher()
        managed_session = _DummyManagedSession()
        acquire_lock = AsyncMock(return_value=False)
        publish_with_session = AsyncMock()

        monkeypatch.setattr(
            "app.services.blog_auto_publish.AsyncSessionLocalBG",
            lambda: _DummySessionContext(managed_session),
        )
        monkeypatch.setattr(publisher, "_acquire_publish_lock", acquire_lock)
        monkeypatch.setattr(publisher, "_publish_with_session", publish_with_session)

        stats = await publisher.publish_daily_posts()

        assert managed_session.begin_calls == 1
        acquire_lock.assert_awaited_once_with(managed_session)
        publish_with_session.assert_not_awaited()
        assert stats["published_count"] == 0
        assert stats["skipped_count"] == 1

    @pytest.mark.asyncio
    async def test_publish_daily_posts_filters_recent_duplicates_before_generation(
        self,
        db_session,
        monkeypatch: pytest.MonkeyPatch,
        test_admin_user,
    ) -> None:
        monkeypatch.setattr(settings, "PERPLEXITY_API_KEY", "test-key")
        monkeypatch.setattr(settings, "AUTO_BLOG_PUBLISHER_USER_ID", test_admin_user.id)
        monkeypatch.setattr(settings, "AUTO_BLOG_MAX_POSTS_PER_RUN", 3)

        existing_payload = BlogPostCreate(
            title="Gurugram office leasing gains pace",
            content="<p>Earlier published content.</p><p>https://example.com/existing-source</p>",
            excerpt="Earlier published content.",
            cover_image_url=None,
            categories=["Real Estate"],
            tags=["Commercial"],
            active=True,
        )
        await create_blog_post(db_session, existing_payload, test_admin_user)
        await db_session.commit()

        publisher = DailyPerplexityBlogPublisher()
        today_label = publisher._format_perplexity_date(publisher._today_ist())
        duplicate_item = DiscoveredNewsItem(
            title="Gurugram office leasing gains pace",
            summary="Duplicate existing story.",
            source_name="Example",
            source_url="https://example.com/existing-source",
            publication_date=today_label,
            why_new="It appears new but overlaps an existing post.",
            citations=["https://example.com/existing-source"],
            tags=["Commercial"],
        )
        valid_item = DiscoveredNewsItem(
            title="Circle rate review sparks fresh Gurugram buyer interest",
            summary="New same-day policy coverage for buyers.",
            source_name="Moneycontrol",
            source_url="https://www.moneycontrol.com/gurugram-circle-rates",
            publication_date=today_label,
            why_new="The policy update was published today.",
            citations=["https://www.moneycontrol.com/gurugram-circle-rates"],
            tags=["Policy"],
        )
        generated_draft = GeneratedBlogDraft(
            title="How the latest circle-rate review affects Gurugram buyers",
            excerpt="A same-day circle-rate update is shaping new buyer conversations in Gurugram.",
            content_html=(
                "<p>The latest circle-rate review is influencing buyer sentiment in Gurugram and "
                "could affect negotiation behavior across several active micro-markets.</p>"
            ),
            tags=["Buyers", "Policy"],
            citations=["https://www.moneycontrol.com/gurugram-circle-rates"],
        )

        monkeypatch.setattr(publisher, "_discover_stories", AsyncMock(return_value=[duplicate_item, valid_item]))
        generate_mock = AsyncMock(return_value=generated_draft)
        monkeypatch.setattr(publisher, "_generate_blog_draft", generate_mock)

        stats = await publisher.publish_daily_posts(db_session)

        assert stats["published_count"] == 1
        assert generate_mock.await_count == 1

    @pytest.mark.asyncio
    async def test_publish_daily_posts_continues_after_generation_failure(
        self,
        db_session,
        monkeypatch: pytest.MonkeyPatch,
        test_admin_user,
    ) -> None:
        monkeypatch.setattr(settings, "PERPLEXITY_API_KEY", "test-key")
        monkeypatch.setattr(settings, "AUTO_BLOG_PUBLISHER_USER_ID", test_admin_user.id)

        publisher = DailyPerplexityBlogPublisher()
        today_label = publisher._format_perplexity_date(publisher._today_ist())
        items = [
            DiscoveredNewsItem(
                title="Bad story",
                summary="This story will fail generation.",
                source_name="Example",
                source_url="https://example.com/bad-story",
                publication_date=today_label,
                why_new="It is new today.",
                citations=["https://example.com/bad-story"],
                tags=["Bad"],
            ),
            DiscoveredNewsItem(
                title="Good story",
                summary="This story will publish successfully.",
                source_name="Example",
                source_url="https://example.com/good-story",
                publication_date=today_label,
                why_new="It is new today.",
                citations=["https://example.com/good-story"],
                tags=["Good"],
            ),
        ]

        async def fake_generate(*, item, today_label: str) -> GeneratedBlogDraft:
            if item.title == "Bad story":
                raise RuntimeError("boom")
            return GeneratedBlogDraft(
                title="Good story post",
                excerpt="A successful post from the second story.",
                content_html=(
                    "<p>The second story published successfully and contains enough grounded detail "
                    "to meet the minimum content length expected by the structured output.</p>"
                ),
                tags=["Good"],
                citations=["https://example.com/good-story"],
            )

        monkeypatch.setattr(publisher, "_discover_stories", AsyncMock(return_value=items))
        monkeypatch.setattr(publisher, "_generate_blog_draft", fake_generate)

        stats = await publisher.publish_daily_posts(db_session)

        assert stats["published_count"] == 1
        assert stats["skipped_count"] == 1
        result = await db_session.execute(select(BlogPost).where(BlogPost.title == "Good story post"))
        assert result.scalar_one().active is True
