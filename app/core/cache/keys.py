"""
Cache key generation utilities with consistent hashing.
"""

import hashlib
import json
from typing import Any

from fastapi import Request


def generate_hash(data: Any) -> str:
    """Generate short MD5 hash from data.

    Args:
        data: Data to hash (dict, list, or any serializable type)

    Returns:
        16-character hex hash string
    """
    if isinstance(data, dict):
        # Sort keys for consistent hashing
        serialized = json.dumps(
            data, sort_keys=True, default=lambda o: getattr(o, "value", str(o))
        )
    else:
        serialized = str(data)
    return hashlib.md5(serialized.encode()).hexdigest()[:16]


def build_cache_key(
    prefix: str,
    *args: Any,
    include_user: bool = False,
    user_id: int | None = None,
    **kwargs: Any,
) -> str:
    """Build a cache key from prefix, positional args, and keyword args.

    Args:
        prefix: Key prefix (e.g., 'amenities', 'properties')
        *args: Positional values to include in key
        include_user: Whether to include user_id in key
        user_id: User ID if include_user is True
        **kwargs: Additional key-value pairs to hash

    Returns:
        Cache key string (e.g., 'amenities:v1:abc123' or 'properties:u5:p1:l20:f4d3c2b1')
    """
    parts = [prefix]

    # Add positional args
    for arg in args:
        if arg is not None:
            parts.append(str(arg))

    # Add user if requested
    if include_user:
        parts.append(f"u{user_id or 0}")

    # Add hash of kwargs if present
    if kwargs:
        # Filter out None values
        filtered = {k: v for k, v in kwargs.items() if v is not None}
        if filtered:
            parts.append(generate_hash(filtered))

    return ":".join(parts)


def build_request_cache_key(
    prefix: str,
    request: Request,
    include_user: bool = False,
    user_id: int | None = None,
    param_names: list[str] | None = None,
) -> str:
    """Build cache key from FastAPI Request object.

    Args:
        prefix: Key prefix
        request: FastAPI Request object
        include_user: Include user in key
        user_id: User ID if authenticated
        param_names: Specific query params to include (None = all)

    Returns:
        Cache key string
    """
    params = dict(request.query_params)

    if param_names:
        params = {k: v for k, v in params.items() if k in param_names}

    return build_cache_key(
        prefix,
        request.url.path,
        include_user=include_user,
        user_id=user_id,
        **params,
    )


class CacheKeyPatterns:
    """Standard cache key patterns for invalidation.

    Use these patterns with cache.delete_pattern() to invalidate
    groups of related cache entries.
    """

    AMENITIES = "amenities:*"
    PROPERTIES = "properties:*"
    PROPERTY_DETAIL = "property:*"
    BLOG_POSTS = "blog:posts:*"
    BLOG_CATEGORIES = "blog:categories:*"
    BLOG_TAGS = "blog:tags:*"
    FAQS = "faqs:*"
    VERSIONS = "versions:*"

    @classmethod
    def for_property(cls, property_id: int) -> str:
        """Get pattern for a specific property's cache entries."""
        return f"property:{property_id}:*"

    @classmethod
    def for_user(cls, user_id: int) -> str:
        """Get pattern for a specific user's cache entries."""
        return f"user:{user_id}:*"

    @classmethod
    def for_prefix(cls, prefix: str) -> str:
        """Get pattern for any prefix."""
        return f"{prefix}:*"
