"""Tests for blog model SEO fields."""

from app.models.blogs import BlogPost
from app.services.blog import _compute_reading_time, _compute_word_count


class TestBlogPostSEOFields:
    def test_compute_word_count_simple(self):
        assert _compute_word_count("<p>Hello world this is a test.</p>") == 6

    def test_compute_word_count_with_html(self):
        count = _compute_word_count("<h2>Title</h2><p>First paragraph.</p><ul><li>Item one</li><li>Item two</li></ul>")
        assert count == 7

    def test_compute_word_count_empty(self):
        assert _compute_word_count("") == 0

    def test_compute_word_count_html_only(self):
        assert _compute_word_count("<p></p>") == 0

    def test_compute_reading_time_short(self):
        assert _compute_reading_time(_compute_word_count("<p>Short post.</p>")) == 1

    def test_compute_reading_time_long(self):
        words = " ".join(["word"] * 500)
        assert _compute_reading_time(_compute_word_count(f"<p>{words}</p>")) == 3

    def test_compute_reading_time_exact(self):
        words = " ".join(["word"] * 400)
        assert _compute_reading_time(_compute_word_count(f"<p>{words}</p>")) == 2

    def test_default_sources_and_seo_metadata(self):
        post = BlogPost(title="Test", slug="test", content="<p>Content.</p>")
        post.sources = [{"url": "https://example.com", "name": "Example"}]
        post.seo_metadata = {"trending_score": 80}
        assert len(post.sources) == 1
        assert post.seo_metadata["trending_score"] == 80

    def test_seo_field_assignment(self):
        post = BlogPost(
            title="Test",
            slug="test",
            content="<p>Content.</p>",
            meta_title="SEO Title",
            meta_description="SEO Description",
            focus_keyword="test keyword",
            canonical_url="https://example.com/canonical",
            og_image_url="https://example.com/og.png",
            reading_time_minutes=5,
            word_count=1000,
        )
        assert post.meta_title == "SEO Title"
        assert post.meta_description == "SEO Description"
        assert post.focus_keyword == "test keyword"
        assert post.canonical_url == "https://example.com/canonical"
        assert post.og_image_url == "https://example.com/og.png"
        assert post.reading_time_minutes == 5
        assert post.word_count == 1000
