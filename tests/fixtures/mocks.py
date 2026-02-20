"""
External service mocks for testing.

Provides fixtures that mock external API calls to:
- Firebase Cloud Messaging (FCM)
- Supabase Storage
- Perplexity AI (blog generation)
- SerpAPI (image search)
- Gemini/GLM (Vastu analysis)
- Redis cache
- Email/SMS services
- MCP context
"""

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from httpx import Response


# =============================================================================
# MCP Context Mocks
# =============================================================================

@pytest.fixture
def mock_mcp_context():
    """
    Mock MCP context for testing MCP server tools.

    Provides a mock context that simulates the MCP request context.
    """
    context = MagicMock()
    context.session = MagicMock()
    context.request_id = "test_request_id"
    yield context


@pytest.fixture
def mock_fcm_send():
    """
    Mock FCM send function for notification tests.

    Captures FCM messages for assertion.
    """
    with patch("app.services.notifications.send_message", new_callable=AsyncMock) as mock:
        mock.return_value = {"success": True, "name": "projects/test/messages/12345"}
        yield mock


# =============================================================================
# Firebase / Push Notifications
# =============================================================================

@pytest.fixture
def mock_firebase_fcm():
    """
    Mock Firebase Cloud Messaging for push notification tests.

    Mocks:
    - Access token retrieval
    - FCM send endpoint
    """
    with patch("app.services.notifications._access_token") as mock_token:
        mock_token.return_value = "mock_fcm_access_token"

        with respx.mock:
            # Mock FCM v1 send endpoint
            respx.post(
                url__regex=r"https://fcm\.googleapis\.com/v1/projects/.*/messages:send"
            ).mock(
                return_value=Response(
                    200,
                    json={"name": "projects/mock-project/messages/mock_message_id"},
                )
            )

            yield


@pytest.fixture
def mock_fcm_failure():
    """Mock FCM to simulate send failures."""
    with patch("app.services.notifications._access_token") as mock_token:
        mock_token.return_value = "mock_fcm_access_token"

        with respx.mock:
            respx.post(
                url__regex=r"https://fcm\.googleapis\.com/v1/projects/.*/messages:send"
            ).mock(
                return_value=Response(
                    404,
                    json={"error": {"code": 404, "message": "Unregistered"}},
                )
            )

            yield


# =============================================================================
# Supabase Storage
# =============================================================================

@pytest.fixture
def mock_supabase_storage():
    """
    Mock Supabase Storage for file upload tests.

    Returns a mock client that simulates successful file uploads.
    """
    with patch("app.services.storage.get_supabase_service_client") as mock:
        mock_storage = MagicMock()

        # Mock upload method
        mock_storage.from_.return_value.upload.return_value = MagicMock(
            path="uploads/test_file.jpg"
        )

        # Mock get public URL
        mock_storage.from_.return_value.get_public_url.return_value = (
            "https://storage.supabase.co/test_bucket/uploads/test_file.jpg"
        )

        # Mock delete method
        mock_storage.from_.return_value.remove.return_value = None

        mock.return_value = mock_storage
        yield mock_storage


# =============================================================================
# AI Services (Gemini, GLM, Perplexity)
# =============================================================================

@pytest.fixture
def mock_gemini_api():
    """
    Mock Google Gemini API for Vastu analysis tests.

    Returns a mock that simulates successful Vastu analysis results.
    """
    with patch("app.services.ai.vastu_analyzer.get_ai_provider") as mock:
        mock_provider = MagicMock()
        mock_provider.supports_vision = True
        mock_provider.complete_json = AsyncMock(
            return_value={
                "floor_plan_analysis": {
                    "plot_shape": "rectangular",
                    "rooms": [
                        {"name": "Living Room", "direction": "North"},
                        {"name": "Bedroom", "direction": "Southwest"},
                        {"name": "Kitchen", "direction": "Southeast"},
                        {"name": "Bathroom", "direction": "Northwest"},
                    ],
                    "entrance": {"direction": "East", "type": "main"},
                    "toilets": {"count": 2, "directions": ["Northwest", "West"]},
                },
                "vastu_score": 7,
                "score_explanation": "Good overall layout with minor adjustments needed.",
                "room_analysis": [
                    {
                        "room": "Living Room",
                        "direction": "North",
                        "status": "good",
                        "analysis": "Well-positioned for positive energy flow.",
                    },
                    {
                        "room": "Kitchen",
                        "direction": "Southeast",
                        "status": "ideal",
                        "analysis": "Ideal placement according to Vastu principles.",
                    },
                ],
                "major_defects": [],
                "remedies": [],
                "improvements": [
                    "Consider adding indoor plants in the northeast corner.",
                ],
                "is_valid_floor_plan": True,
                "analysis_confidence": 0.85,
            }
        )
        mock.return_value = mock_provider
        yield mock_provider


@pytest.fixture
def mock_perplexity_api():
    """
    Mock Perplexity AI API for blog generation tests.

    Simulates successful blog content generation.
    """
    with respx.mock:
        respx.post("https://api.perplexity.ai/chat/completions").mock(
            return_value=Response(
                200,
                json={
                    "id": "mock-completion-id",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": """# Test Blog Post

## Introduction

This is a mock blog post generated for testing purposes.

## Key Points

1. First important point
2. Second important point
3. Third important point

## Conclusion

Thank you for reading this test blog post.
""",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 200,
                        "total_tokens": 300,
                    },
                },
            )
        )
        yield


@pytest.fixture
def mock_serpapi():
    """
    Mock SerpAPI for image search tests.

    Simulates image search results.
    """
    with respx.mock:
        respx.get(url__regex=r"https://serpapi\.com/search.*").mock(
            return_value=Response(
                200,
                json={
                    "images_results": [
                        {
                            "position": 1,
                            "thumbnail": "https://example.com/thumb1.jpg",
                            "original": "https://example.com/image1.jpg",
                            "title": "Test Image 1",
                            "link": "https://example.com/page1",
                        },
                        {
                            "position": 2,
                            "thumbnail": "https://example.com/thumb2.jpg",
                            "original": "https://example.com/image2.jpg",
                            "title": "Test Image 2",
                            "link": "https://example.com/page2",
                        },
                    ],
                    "search_metadata": {
                        "status": "Success",
                        "total_time_taken": 0.5,
                    },
                },
            )
        )
        yield


# =============================================================================
# Redis Cache
# =============================================================================

@pytest.fixture
def mock_redis():
    """
    Mock Redis client for cache tests.

    Provides an in-memory mock of Redis operations.
    """
    # Storage for mock data
    mock_data: Dict[str, Any] = {}

    with patch("app.core.cache.backends.redis.redis.asyncio.from_url") as mock:
        mock_redis = AsyncMock()

        async def mock_get(key: str) -> Optional[bytes]:
            value = mock_data.get(key)
            if value is None:
                return None
            return value.encode() if isinstance(value, str) else value

        async def mock_set(
            key: str,
            value: Any,
            ex: Optional[int] = None,
        ) -> bool:
            mock_data[key] = value
            return True

        async def mock_delete(*keys: str) -> int:
            count = 0
            for key in keys:
                if key in mock_data:
                    del mock_data[key]
                    count += 1
            return count

        async def mock_exists(*keys: str) -> int:
            return sum(1 for key in keys if key in mock_data)

        async def mock_keys(pattern: str) -> List[bytes]:
            import fnmatch

            return [
                k.encode() for k in mock_data.keys()
                if fnmatch.fnmatch(k, pattern.replace("*", ".*"))
            ]

        async def mock_flushdb() -> bool:
            mock_data.clear()
            return True

        mock_redis.get = mock_get
        mock_redis.set = mock_set
        mock_redis.delete = mock_delete
        mock_redis.exists = mock_exists
        mock_redis.keys = mock_keys
        mock_redis.flushdb = mock_flushdb
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.close = AsyncMock()

        mock.return_value = mock_redis
        yield mock_redis


@pytest.fixture
def mock_cache_manager():
    """
    Mock the entire cache manager.

    Useful when you want to bypass caching entirely.
    """
    with patch("app.core.cache.manager.CacheManager") as mock_class:
        mock = MagicMock()
        mock.get = AsyncMock(return_value=None)
        mock.set = AsyncMock(return_value=True)
        mock.delete = AsyncMock(return_value=True)
        mock.clear = AsyncMock(return_value=True)
        mock.invalidate_pattern = AsyncMock(return_value=0)
        mock_class.return_value = mock
        yield mock


# =============================================================================
# Email / SMS Services
# =============================================================================

@pytest.fixture
def mock_email_service():
    """
    Mock email sending service.

    Captures sent emails for assertion.
    """
    sent_emails: List[Dict[str, Any]] = []

    with patch("app.services.email.send_email") as mock:

        async def capture_email(
            to: str,
            subject: str,
            body: str,
            **kwargs,
        ) -> bool:
            sent_emails.append({
                "to": to,
                "subject": subject,
                "body": body,
                **kwargs,
            })
            return True

        mock.side_effect = capture_email
        mock.sent_emails = sent_emails
        yield mock


@pytest.fixture
def mock_sms_service():
    """
    Mock SMS sending service.

    Captures sent SMS for assertion.
    """
    sent_sms: List[Dict[str, Any]] = []

    with patch("app.services.sms.send_sms") as mock:

        async def capture_sms(
            phone: str,
            message: str,
            **kwargs,
        ) -> bool:
            sent_sms.append({
                "phone": phone,
                "message": message,
                **kwargs,
            })
            return True

        mock.side_effect = capture_sms
        mock.sent_sms = sent_sms
        yield mock


# =============================================================================
# Rate Limiter
# =============================================================================

@pytest.fixture
def mock_rate_limiter():
    """
    Mock rate limiter to always allow requests.

    Useful for testing endpoints without rate limit interference.
    """
    with patch("app.middleware.rate_limit.RateLimitMiddleware") as mock:
        # Make the middleware pass-through
        mock.return_value = None
        yield mock


@pytest.fixture
def disable_rate_limit():
    """
    Disable rate limiting for tests.

    Patches the check method to always return allowed.
    """
    with patch(
        "app.middleware.rate_limit.RateLimitMiddleware._is_rate_limited"
    ) as mock:
        mock.return_value = False
        yield mock
