"""
Tests for blog endpoints.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import SQLAlchemyError


class TestBlogPostEndpoints:
    """Tests for blog post CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_list_blog_posts(self, client: AsyncClient):
        """Test listing blog posts."""
        with patch(
            "app.api.api_v1.endpoints.blog.list_blog_posts",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, None)

            response = await client.get("/api/v1/blog/posts")

            assert response.status_code == 200
            data = response.json()
            assert "items" in data
            assert "has_more" in data

    @pytest.mark.asyncio
    async def test_list_blog_posts_with_filters(self, client: AsyncClient):
        """Test listing blog posts with filters."""
        with patch(
            "app.api.api_v1.endpoints.blog.list_blog_posts",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, None)

            response = await client.get(
                "/api/v1/blog/posts",
                params={
                    "q": "real estate",
                    "categories": ["buying-guide"],
                    "limit": 10,
                },
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_blog_posts_returns_503_for_transient_db_error(self, client: AsyncClient):
        # Public non-admin requests with no include_total go through list_posts_cached.
        with patch(
            "app.api.api_v1.endpoints.blog.list_posts_cached",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.side_effect = SQLAlchemyError(
                "(EDBHANDLEREXITED) connection to database closed"
            )

            response = await client.get("/api/v1/blog/posts")
            assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_get_blog_post(self, client: AsyncClient):
        """Test getting a specific blog post."""
        with patch(
            "app.api.api_v1.endpoints.blog.get_blog_post_cached",
            new_callable=AsyncMock,
        ) as mock_get:
            # Return a dict that can be serialized
            mock_get.return_value = {
                "id": 1,
                "title": "Test Post",
                "slug": "test-post",
                "content": "Content here with enough characters",
                "excerpt": "Excerpt here",
                "active": True,
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": None,
                "categories": [],
                "tags": [],
            }

            response = await client.get("/api/v1/blog/posts/test-post")

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_blog_post_not_found(self, client: AsyncClient):
        """Test getting a non-existent blog post."""
        with patch(
            "app.api.api_v1.endpoints.blog.get_blog_post",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None

            response = await client.get("/api/v1/blog/posts/non-existent")

            assert response.status_code == 404


class TestBlogCategoryEndpoints:
    """Tests for blog category endpoints."""

    @pytest.mark.asyncio
    async def test_list_categories(self, client: AsyncClient):
        """Test listing blog categories."""
        with patch(
            "app.api.api_v1.endpoints.blog.list_categories",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, None)

            response = await client.get("/api/v1/blog/categories")

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_category_not_found(self, client: AsyncClient):
        """Test getting a non-existent category."""
        with patch(
            "app.api.api_v1.endpoints.blog.get_category",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None

            response = await client.get("/api/v1/blog/categories/non-existent")

            assert response.status_code == 404


class TestBlogTagEndpoints:
    """Tests for blog tag endpoints."""

    @pytest.mark.asyncio
    async def test_list_tags(self, client: AsyncClient):
        """Test listing blog tags."""
        with patch(
            "app.api.api_v1.endpoints.blog.list_tags",
            new_callable=AsyncMock,
        ) as mock_list:
            mock_list.return_value = ([], None, None)

            response = await client.get("/api/v1/blog/tags")

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_tag_not_found(self, client: AsyncClient):
        """Test getting a non-existent tag."""
        with patch(
            "app.api.api_v1.endpoints.blog.get_tag",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None

            response = await client.get("/api/v1/blog/tags/non-existent")

            assert response.status_code == 404
