from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import AsyncSessionLocalBG
from app.core.logging import get_logger
from app.models.blogs import BlogPost
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.blog import BlogPostCreate
from app.services.blog import create_blog_post
from app.utils.validators import ValidationUtils

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
RECENT_POST_LOOKBACK_DAYS = 7
DATE_FORMAT = "%m/%d/%Y"
DEFAULT_CATEGORIES = ["Real Estate", "Gurugram", "News"]
DEFAULT_TAGS = ["Real Estate", "Gurugram", "News"]
BLOCKED_SOURCE_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "medium.com",
    "reddit.com",
    "t.co",
    "telegram.me",
    "telegram.org",
    "threads.net",
    "x.com",
    "youtu.be",
    "youtube.com",
}
AUTO_BLOG_PUBLISH_LOCK_KEY = "auto_blog_publish"
STOP_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "from",
    "how",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
DISCOVERY_SYSTEM_PROMPT = """
You are the automated news desk for 360 Ghar.

Your job is to discover only fresh, same-day Real Estate and Gurugram stories that can become blog posts.

Rules:
- Use web-grounded information only.
- Return only stories published on the exact date requested by the user.
- Exclude stories that overlap with the recent published-article list provided by the user.
- Prefer official/government, mainstream business, and reputable local news sources.
- Do not return social posts, opinion-only posts, or pages without clear sourcing.
- Return valid structured data only.
""".strip()
GENERATION_SYSTEM_PROMPT = """
You are a factual real-estate blog writer for 360 Ghar.

Write publish-ready HTML articles grounded only in the supplied, current web information.

Rules:
- Do not invent facts, numbers, dates, projects, policy details, or quotes.
- If something is uncertain, omit it.
- Use clean HTML with <p>, <h2>, <h3>, <ul>, <ol>, <li>, <strong>, <em>, and <a>.
- Keep the tone clear, direct, and professional.
- Focus on why the story matters for Real Estate and Gurugram readers.
- Return valid structured data only.
""".strip()


class DiscoveredNewsItem(BaseModel):
    title: str = Field(..., min_length=8)
    summary: str = Field(..., min_length=16)
    source_name: str = Field(..., min_length=2)
    source_url: str = Field(..., min_length=8)
    publication_date: str = Field(..., min_length=8)
    why_new: str = Field(..., min_length=12)
    citations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class DiscoveredNewsBatch(BaseModel):
    items: list[DiscoveredNewsItem] = Field(default_factory=list)


class GeneratedBlogDraft(BaseModel):
    title: str = Field(..., min_length=8)
    excerpt: str = Field(..., min_length=20)
    content_html: str = Field(..., min_length=64)
    tags: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class AutoBlogRunStats(BaseModel):
    discovered_count: int = 0
    filtered_count: int = 0
    published_count: int = 0
    skipped_count: int = 0
    published_titles: list[str] = Field(default_factory=list)


class RecentPublishedPost(BaseModel):
    title: str
    slug: str
    excerpt: str | None = None
    source_urls: list[str] = Field(default_factory=list)


class PerplexitySonarChatModel(OpenAIChatModel):
    """Preserve Perplexity-specific metadata on the model response."""

    def _process_provider_details(self, response: Any) -> dict[str, Any] | None:
        provider_details = super()._process_provider_details(response) or {}
        raw_response = response.to_dict() if hasattr(response, "to_dict") else {}

        citations = raw_response.get("citations")
        search_results = raw_response.get("search_results")

        if not citations and getattr(response, "model_extra", None):
            citations = response.model_extra.get("citations")
        if not search_results and getattr(response, "model_extra", None):
            search_results = response.model_extra.get("search_results")

        if citations:
            provider_details["citations"] = [str(item).strip() for item in citations if str(item).strip()]
        if search_results:
            provider_details["search_results"] = search_results
        return provider_details or None


class DailyPerplexityBlogPublisher:
    def __init__(self) -> None:
        self._provider = OpenAIProvider(
            api_key=settings.PERPLEXITY_API_KEY,
            base_url="https://api.perplexity.ai",
        )

    async def publish_daily_posts(self, db: AsyncSession | None = None) -> dict[str, Any]:
        if not settings.PERPLEXITY_API_KEY:
            logger.warning("Auto blog publish skipped because PERPLEXITY_API_KEY is not configured")
            return AutoBlogRunStats(skipped_count=1).model_dump()

        if db is None:
            async with AsyncSessionLocalBG() as session:
                async with session.begin():
                    got_lock = await self._acquire_publish_lock(session)
                    if not got_lock:
                        return AutoBlogRunStats(skipped_count=1).model_dump()
                    return await self._publish_with_session(session, manage_commit=False)
        return await self._publish_with_session(db, manage_commit=False)

    async def _acquire_publish_lock(self, db: AsyncSession) -> bool:
        result = await db.execute(
            text(
                "SELECT pg_try_advisory_xact_lock(hashtext(:lock_key))"
            ),
            {"lock_key": AUTO_BLOG_PUBLISH_LOCK_KEY},
        )
        got_lock = bool(result.scalar_one())
        if not got_lock:
            logger.info("Auto blog publish skipped; another worker holds the advisory lock")
        return got_lock

    async def _publish_with_session(self, db: AsyncSession, *, manage_commit: bool) -> dict[str, Any]:
        stats = AutoBlogRunStats()
        today = self._today_ist()
        today_label = self._format_perplexity_date(today)
        publisher = await self._get_publisher_user(db)
        if publisher is None:
            logger.warning(
                "Auto blog publish skipped because publisher user is unavailable",
                extra={"publisher_user_id": settings.AUTO_BLOG_PUBLISHER_USER_ID},
            )
            stats.skipped_count += 1
            return stats.model_dump()

        recent_posts = await self._get_recent_published_posts(db)
        discovered = await self._discover_stories(
            recent_posts=recent_posts,
            today_label=today_label,
            max_items=settings.AUTO_BLOG_MAX_POSTS_PER_RUN,
        )
        stats.discovered_count = len(discovered)

        filtered_candidates = self._filter_discovered_items(
            items=discovered,
            recent_posts=recent_posts,
            today=today,
        )
        stats.filtered_count = len(filtered_candidates)

        for item in filtered_candidates[: settings.AUTO_BLOG_MAX_POSTS_PER_RUN]:
            try:
                draft = await self._generate_blog_draft(item=item, today_label=today_label)
                payload = self._build_blog_payload(item=item, draft=draft)
                async with db.begin_nested():
                    created = await create_blog_post(db, payload, publisher)
                if manage_commit:
                    await db.commit()
                else:
                    await db.flush()

                stats.published_count += 1
                stats.published_titles.append(created.title)
                recent_posts.append(
                    RecentPublishedPost(
                        title=created.title,
                        slug=created.slug,
                        excerpt=created.excerpt,
                        source_urls=self._unique_urls(draft.citations or item.citations),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                stats.skipped_count += 1
                logger.error(
                    "Failed to publish auto-generated blog story",
                    exc_info=True,
                    extra={"story_title": item.title, "error": str(exc)},
                )

        if stats.published_count == 0 and stats.filtered_count == 0:
            stats.skipped_count += 1

        return stats.model_dump()

    async def _get_publisher_user(self, db: AsyncSession) -> User | None:
        publisher_user_id = settings.AUTO_BLOG_PUBLISHER_USER_ID
        if publisher_user_id is None:
            return None

        result = await db.execute(select(User).where(User.id == publisher_user_id))
        user = result.scalar_one_or_none()
        if user is None or user.role != UserRole.admin.value:
            return None
        return user

    async def _get_recent_published_posts(self, db: AsyncSession) -> list[RecentPublishedPost]:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=RECENT_POST_LOOKBACK_DAYS)
        result = await db.execute(
            select(BlogPost)
            .where(BlogPost.active.is_(True), BlogPost.created_at >= cutoff)
            .order_by(BlogPost.created_at.desc())
        )
        posts = result.scalars().all()
        return [
            RecentPublishedPost(
                title=post.title,
                slug=post.slug,
                excerpt=post.excerpt,
                source_urls=self._extract_urls(post.content),
            )
            for post in posts
        ]

    async def _discover_stories(
        self,
        *,
        recent_posts: list[RecentPublishedPost],
        today_label: str,
        max_items: int,
    ) -> list[DiscoveredNewsItem]:
        agent = Agent(
            self._build_model(),
            output_type=NativeOutput(DiscoveredNewsBatch),
            system_prompt=DISCOVERY_SYSTEM_PROMPT,
            retries=2,
        )
        prompt = self._build_discovery_prompt(
            recent_posts=recent_posts,
            today_label=today_label,
            max_items=max_items,
        )
        result = await agent.run(
            prompt,
            model_settings={
                "temperature": 0.0,
                "max_tokens": 4000,
                "extra_body": {
                    "return_citations": True,
                    "return_related_questions": False,
                    "search_after_date_filter": today_label,
                    "search_before_date_filter": today_label,
                },
            },
        )
        output = result.output
        provider_citations = self._result_citations(result)
        items: list[DiscoveredNewsItem] = []
        for item in output.items:
            if not item.citations and provider_citations:
                item.citations = provider_citations
            items.append(item)
        return items

    async def _generate_blog_draft(
        self,
        *,
        item: DiscoveredNewsItem,
        today_label: str,
    ) -> GeneratedBlogDraft:
        agent = Agent(
            self._build_model(),
            output_type=NativeOutput(GeneratedBlogDraft),
            system_prompt=GENERATION_SYSTEM_PROMPT,
            retries=2,
        )
        prompt = self._build_generation_prompt(item=item, today_label=today_label)
        result = await agent.run(
            prompt,
            model_settings={
                "temperature": 0.1,
                "max_tokens": 6000,
                "extra_body": {
                    "return_citations": True,
                    "return_related_questions": False,
                    "search_after_date_filter": today_label,
                    "search_before_date_filter": today_label,
                },
            },
        )
        draft = result.output
        citations = self._unique_urls([*draft.citations, *item.citations, *self._result_citations(result)])
        draft.citations = citations
        return draft

    def _build_model(self) -> PerplexitySonarChatModel:
        return PerplexitySonarChatModel(
            settings.AUTO_BLOG_MODEL,
            provider=self._provider,
        )

    def _build_discovery_prompt(
        self,
        *,
        recent_posts: list[RecentPublishedPost],
        today_label: str,
        max_items: int,
    ) -> str:
        recent_articles = self._format_recent_posts(recent_posts)
        return (
            f"Today's IST date is {today_label}.\n"
            f"Find up to {max_items} distinct news updates or market developments that are specifically relevant "
            "to Real Estate and Gurugram.\n\n"
            "Only include stories that were published on the exact same date above.\n"
            "Skip anything that overlaps with the already-published articles below.\n\n"
            "Return the most relevant items first.\n\n"
            "Already published in the last 7 days:\n"
            f"{recent_articles}"
        )

    def _build_generation_prompt(self, *, item: DiscoveredNewsItem, today_label: str) -> str:
        return (
            f"Today's IST date is {today_label}.\n"
            "Write one publish-ready 360 Ghar blog post for the story below.\n\n"
            f"Story title: {item.title}\n"
            f"Story summary: {item.summary}\n"
            f"Primary source: {item.source_name}\n"
            f"Primary source URL: {item.source_url}\n"
            f"Publication date: {item.publication_date}\n"
            f"Why this is new: {item.why_new}\n"
            f"Known citations: {', '.join(item.citations) if item.citations else item.source_url}\n\n"
            "Requirements:\n"
            "- Ground every factual statement in current web information.\n"
            "- Focus on what changed today and why it matters.\n"
            "- Keep the HTML clean and ready for storage.\n"
            "- Include a concise excerpt.\n"
            "- Return useful tags for the article.\n"
            "- Include source URLs in the citations field.\n"
        )

    def _build_blog_payload(self, *, item: DiscoveredNewsItem, draft: GeneratedBlogDraft) -> BlogPostCreate:
        from app.schemas.blog import BlogSEOMetadata, BlogSource

        citations = self._unique_urls([*draft.citations, *item.citations, item.source_url])
        content_html = self._append_sources_section(draft.content_html, citations)
        sanitized_content = ValidationUtils.sanitize_html(content_html)
        excerpt = draft.excerpt.strip() or self._build_excerpt(sanitized_content)
        tags = self._merge_tags(DEFAULT_TAGS, item.tags, draft.tags)
        today_iso = self._today_ist().isoformat()

        # Build structured sources
        sources = []
        for url in citations:
            parsed = urlparse(url)
            sources.append(BlogSource(
                url=url,
                name=parsed.netloc or url,
                type="article",
                retrieved_at=today_iso,
            ))
        # Mark the primary source
        if item.source_url:
            for s in sources:
                if s.url == item.source_url:
                    s.type = "primary"
                    break

        # Build SEO metadata
        meta_title = draft.title.strip()[:60]
        meta_description = excerpt[:160]
        focus_keyword = " ".join(item.tags[:2]) if item.tags else None
        seo_metadata = BlogSEOMetadata(
            trending_score=70.0,
            secondary_keywords=item.tags,
            schema_markup=None,
            keyword_analysis=None,
            internal_links=None,
            custom_data=None,
        )

        return BlogPostCreate(
            title=draft.title.strip(),
            content=sanitized_content,
            excerpt=excerpt,
            cover_image_url=None,
            categories=list(DEFAULT_CATEGORIES),
            tags=tags,
            active=True,
            meta_title=meta_title,
            meta_description=meta_description,
            focus_keyword=focus_keyword,
            sources=sources,
            seo_metadata=seo_metadata,
            canonical_url=None,
            og_image_url=None,
            published_at=None,
        )

    def _filter_discovered_items(
        self,
        *,
        items: list[DiscoveredNewsItem],
        recent_posts: list[RecentPublishedPost],
        today: date,
    ) -> list[DiscoveredNewsItem]:
        filtered: list[DiscoveredNewsItem] = []
        seen_titles: set[str] = set()
        seen_urls: set[str] = set()

        for item in items:
            normalized_title = self._normalize_text(item.title)
            source_url = item.source_url.strip()

            if not normalized_title or normalized_title in seen_titles:
                continue
            if not source_url or source_url in seen_urls:
                continue
            if not item.citations:
                continue
            if not self._matches_today(item.publication_date, today):
                continue
            if self._is_blocked_source(source_url):
                continue
            if self._overlaps_recent_posts(item, recent_posts):
                continue

            seen_titles.add(normalized_title)
            seen_urls.add(source_url)
            filtered.append(item)

        return filtered

    def _overlaps_recent_posts(
        self,
        item: DiscoveredNewsItem,
        recent_posts: list[RecentPublishedPost],
    ) -> bool:
        item_title = self._normalize_text(item.title)
        item_keywords = self._keywords(item.title)
        item_source_url = item.source_url.strip()

        for post in recent_posts:
            if item_source_url and item_source_url in post.source_urls:
                return True

            post_title = self._normalize_text(post.title)
            if item_title == post_title or item_title in post_title or post_title in item_title:
                return True

            if len(item_keywords & self._keywords(post.title)) >= 3:
                return True

        return False

    def _format_recent_posts(self, recent_posts: list[RecentPublishedPost]) -> str:
        if not recent_posts:
            return "- None"
        lines = []
        for post in recent_posts:
            excerpt = (post.excerpt or "").strip()
            excerpt_suffix = f" | excerpt: {excerpt}" if excerpt else ""
            lines.append(f"- {post.title} | slug: {post.slug}{excerpt_suffix}")
        return "\n".join(lines)

    def _append_sources_section(self, content_html: str, citations: Iterable[str]) -> str:
        unique_citations = self._unique_urls(citations)
        if not unique_citations:
            return content_html

        lower_html = content_html.lower()
        if "<h2>sources</h2>" in lower_html or "<h3>sources</h3>" in lower_html:
            return content_html

        items = []
        for url in unique_citations:
            label = urlparse(url).netloc or url
            items.append(f'<li><a href="{escape(url, quote=True)}">{escape(label)}</a></li>')
        sources_html = "<h2>Sources</h2><ul>" + "".join(items) + "</ul>"
        return f"{content_html.rstrip()}{sources_html}"

    def _result_citations(self, result: Any) -> list[str]:
        for message in reversed(result.all_messages()):
            if isinstance(message, ModelResponse):
                provider_details = message.provider_details or {}
                return self._unique_urls(provider_details.get("citations") or [])
        return []

    def _unique_urls(self, values: Iterable[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for value in values:
            url = str(value).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            unique.append(url)
        return unique

    def _is_blocked_source(self, source_url: str) -> bool:
        domain = urlparse(source_url).netloc.lower().removeprefix("www.")
        return any(domain == blocked or domain.endswith(f".{blocked}") for blocked in BLOCKED_SOURCE_DOMAINS)

    def _matches_today(self, publication_date: str, today: date) -> bool:
        normalized = publication_date.strip()
        accepted_formats = (
            DATE_FORMAT,
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%B %d, %Y",
            "%b %d, %Y",
        )
        for fmt in accepted_formats:
            try:
                return datetime.strptime(normalized, fmt).date() == today
            except ValueError:
                continue
        return False

    def _extract_urls(self, content: str) -> list[str]:
        return self._unique_urls(re.findall(r"https?://[^\s\"'<>]+", content or ""))

    def _merge_tags(self, *groups: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for raw_tag in group:
                tag = raw_tag.strip()
                if not tag:
                    continue
                key = tag.lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(tag)
        return merged

    def _build_excerpt(self, html_content: str, max_length: int = 280) -> str:
        text = re.sub(r"<[^>]+>", " ", html_content or "")
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_length].rstrip()

    def _keywords(self, value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", value.lower())
            if len(token) >= 3 and token not in STOP_WORDS
        }

    def _normalize_text(self, value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.lower()))

    def _today_ist(self) -> date:
        return datetime.now(IST).date()

    def _format_perplexity_date(self, value: date) -> str:
        return value.strftime(DATE_FORMAT)
