"""Tests for blog schema SEO fields and validation."""

from app.schemas.blog import (
    BlogPostCreate,
    BlogPostUpdate,
    BlogSEOMetadata,
    BlogSource,
)


class TestBlogSource:
    def test_valid_source(self):
        source = BlogSource(url="https://example.com/article", name="Example", type="article", retrieved_at="2026-05-13")
        assert source.url == "https://example.com/article"
        assert source.type == "article"

    def test_minimal_source(self):
        source = BlogSource(url="https://example.com")
        assert source.name == ""
        assert source.type == "article"

    def test_source_type_variants(self):
        for t in ("article", "government", "data", "image", "video", "other", "primary"):
            source = BlogSource(url="https://example.com", type=t)
            assert source.type == t


class TestBlogSEOMetadata:
    def test_empty_metadata(self):
        meta = BlogSEOMetadata()
        assert meta.schema_markup is None
        assert meta.trending_score is None

    def test_full_metadata(self):
        meta = BlogSEOMetadata(
            schema_markup={"@type": "Article"},
            keyword_analysis={"volume": "high"},
            trending_score=85.0,
            secondary_keywords=["gurgaon property", "sector 79"],
            internal_links=["existing-blog-slug"],
        )
        assert meta.trending_score == 85.0
        assert len(meta.secondary_keywords) == 2
        assert meta.internal_links == ["existing-blog-slug"]

    def test_custom_data(self):
        meta = BlogSEOMetadata(custom_data={"ai_generated": True})
        assert meta.custom_data == {"ai_generated": True}


class TestBlogPostCreateSEOFields:
    def test_create_with_seo_fields(self):
        payload = BlogPostCreate(
            title="Test Post",
            content="<p>Content here is long enough to pass validation.</p>",
            meta_title="SEO Title",
            meta_description="SEO description for SERP",
            focus_keyword="test keyword",
            canonical_url="https://example.com/canonical",
            og_image_url="https://example.com/og.png",
            sources=[BlogSource(url="https://example.com", name="Example")],
            seo_metadata=BlogSEOMetadata(trending_score=75.0),
            categories=["Real Estate"],
            tags=["test"],
        )
        assert payload.meta_title == "SEO Title"
        assert payload.focus_keyword == "test keyword"
        assert len(payload.sources) == 1
        assert payload.seo_metadata.trending_score == 75.0

    def test_create_minimal(self):
        payload = BlogPostCreate(
            title="Test Post",
            content="<p>Minimal content for testing.</p>",
        )
        assert payload.meta_title is None
        assert payload.sources is None
        assert payload.seo_metadata is None

    def test_meta_title_max_length(self):
        payload = BlogPostCreate(
            title="Test Post",
            content="<p>Content here.</p>",
            meta_title="A" * 60,
        )
        assert len(payload.meta_title) == 60

    def test_meta_description_max_length(self):
        payload = BlogPostCreate(
            title="Test Post",
            content="<p>Content here.</p>",
            meta_description="B" * 160,
        )
        assert len(payload.meta_description) == 160

    def test_published_at_field(self):
        from datetime import UTC, datetime
        now = datetime.now(UTC)
        payload = BlogPostCreate(
            title="Test Post",
            content="<p>Content here.</p>",
            published_at=now,
            active=True,
        )
        assert payload.published_at == now


class TestBlogPostUpdateSEOFields:
    def test_update_seo_fields(self):
        payload = BlogPostUpdate(
            meta_title="Updated SEO Title",
            meta_description="Updated description",
            focus_keyword="new keyword",
            sources=[BlogSource(url="https://example.com")],
            seo_metadata=BlogSEOMetadata(trending_score=90.0),
        )
        assert payload.meta_title == "Updated SEO Title"
        assert payload.seo_metadata.trending_score == 90.0

    def test_partial_update(self):
        payload = BlogPostUpdate(focus_keyword="only keyword")
        assert payload.title is None
        assert payload.content is None
        assert payload.focus_keyword == "only keyword"
