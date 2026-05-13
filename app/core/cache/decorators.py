"""
Caching decorators for FastAPI endpoints and service functions.
"""

import functools
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.core.cache.keys import build_cache_key
from app.core.logging import get_logger

logger = get_logger(__name__)

# Type variable for return types
T = TypeVar("T")


def cached(
    prefix: str,
    ttl: int = 300,
    key_params: list[str] | None = None,
    include_user: bool = False,
    cache_none: bool = False,
    condition: Callable[..., bool] | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator for caching async function results.

    Args:
        prefix: Cache key prefix
        ttl: Time-to-live in seconds
        key_params: Specific kwargs to include in key (None = all serializable)
        include_user: Include current_user in cache key
        cache_none: Whether to cache None results
        condition: Optional callable to determine if result should be cached

    Usage:
        @cached("amenities", ttl=86400)
        async def get_all_amenities(db: AsyncSession):
            ...

        @cached("properties", ttl=300, key_params=["city", "purpose"])
        async def search_properties(db: AsyncSession, city: str, purpose: str):
            ...
    """

    def decorator(
        func: Callable[..., Awaitable[T]],
    ) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            # Import here to avoid circular imports
            from app.core.cache import get_cache_manager

            cache = get_cache_manager()

            if not cache.is_available():
                return await func(*args, **kwargs)

            # Build cache key
            user_id = None
            if include_user and "current_user" in kwargs:
                user = kwargs.get("current_user")
                user_id = getattr(user, "id", None) if user else None

            # Extract relevant kwargs for key
            if key_params:
                key_kwargs = {k: kwargs.get(k) for k in key_params}
            else:
                # Exclude non-serializable objects
                key_kwargs = {
                    k: v
                    for k, v in kwargs.items()
                    if k not in ("db", "current_user", "request", "session")
                }

            cache_key = build_cache_key(
                prefix,
                include_user=include_user,
                user_id=user_id,
                **key_kwargs,
            )

            # Try cache
            try:
                cached_value = await cache.get(cache_key)
                if cached_value is not None:
                    logger.debug("Cache hit: %s", cache_key)
                    return cached_value  # type: ignore[no-any-return]
            except Exception as e:
                logger.warning("Cache get error: %s", e)

            # Execute function
            result = await func(*args, **kwargs)

            # Check caching condition
            should_cache = True
            if result is None and not cache_none:
                should_cache = False
            if condition and not condition(result):
                should_cache = False

            # Store in cache
            if should_cache:
                try:
                    # Serialize Pydantic models
                    cache_value = _serialize_for_cache(result)
                    await cache.set(cache_key, cache_value, ttl)
                    logger.debug("Cache set: %s", cache_key)
                except Exception as e:
                    logger.warning("Cache set error: %s", e)

            return result

        return wrapper

    return decorator


def invalidate_cache(patterns: str | list[str]) -> Callable:
    """Decorator to invalidate cache patterns after function execution.

    Args:
        patterns: Cache key pattern or list of patterns to invalidate

    Usage:
        @invalidate_cache("properties:*")
        @invalidate_cache(["properties:*"])
        async def create_property(...):
            ...
    """

    normalized_patterns = [patterns] if isinstance(patterns, str) else list(patterns)

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await func(*args, **kwargs)

            # Invalidate after successful execution
            from app.core.cache import get_cache_manager

            cache = get_cache_manager()

            for pattern in normalized_patterns:
                try:
                    deleted = await cache.delete_pattern(pattern)
                    if deleted > 0:
                        logger.debug("Invalidated %s keys for pattern: %s", deleted, pattern)
                except Exception as e:
                    logger.warning("Cache invalidation error for %s: %s", pattern, e)

            return result

        return wrapper

    return decorator


def _serialize_for_cache(value: Any) -> Any:
    """Serialize value for cache storage.

    Handles Pydantic models, lists of models, and dicts.
    """
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    elif isinstance(value, list):
        return [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            for item in value
        ]
    elif isinstance(value, dict):
        return {
            k: _serialize_for_cache(v)
            for k, v in value.items()
        }
    return value
