from app.core.cache import PropertyCacheManager
from app.schemas.property import SortBy
from datetime import datetime
from enum import Enum


def test_property_cache_key_is_stable_for_filter_order() -> None:
    filters_a = {
        "city": "Gurgaon",
        "purpose": "rent",
        "price_min": 10000,
        "sort_by": SortBy.newest,
    }
    filters_b = {
        "sort_by": SortBy.newest,
        "price_min": 10000,
        "purpose": "rent",
        "city": "Gurgaon",
    }

    key_a = PropertyCacheManager.generate_cache_key(filters_a, user_id=0, page=1, limit=20)
    key_b = PropertyCacheManager.generate_cache_key(filters_b, user_id=0, page=1, limit=20)

    assert key_a == key_b


def test_property_cache_key_changes_with_user() -> None:
    """Different users should get different cache keys."""
    filters = {"city": "Gurgaon", "purpose": "rent"}

    k1 = PropertyCacheManager.generate_cache_key(filters, user_id=0, page=1, limit=20)
    k2 = PropertyCacheManager.generate_cache_key(filters, user_id=1, page=1, limit=20)

    assert k1 != k2


def test_property_cache_key_changes_with_page() -> None:
    """Different pages should get different cache keys."""
    filters = {"city": "Gurgaon", "purpose": "rent"}

    k1 = PropertyCacheManager.generate_cache_key(filters, user_id=0, page=1, limit=20)
    k3 = PropertyCacheManager.generate_cache_key(filters, user_id=0, page=2, limit=20)

    assert k1 != k3


def test_property_cache_key_changes_with_limit() -> None:
    """Different limits should get different cache keys."""
    filters = {"city": "Gurgaon", "purpose": "rent"}

    k1 = PropertyCacheManager.generate_cache_key(filters, user_id=0, page=1, limit=20)
    k4 = PropertyCacheManager.generate_cache_key(filters, user_id=0, page=1, limit=10)

    assert k1 != k4


def test_property_cache_key_handles_enum_values() -> None:
    """Cache key should handle enum values correctly."""
    filters_a = {"sort_by": SortBy.newest, "purpose": "rent"}
    filters_b = {"sort_by": SortBy.price_low, "purpose": "rent"}

    key_a = PropertyCacheManager.generate_cache_key(filters_a, user_id=0, page=1, limit=20)
    key_b = PropertyCacheManager.generate_cache_key(filters_b, user_id=0, page=1, limit=20)

    assert key_a != key_b


def test_property_cache_key_handles_nested_values() -> None:
    """Cache key should handle nested dict/list values."""
    filters = {
        "city": "Delhi",
        "amenities": ["wifi", "parking", "gym"],
        "price_range": {"min": 10000, "max": 50000},
    }

    key = PropertyCacheManager.generate_cache_key(filters, user_id=1, page=1, limit=20)
    assert key is not None
    assert isinstance(key, str)
    assert key.startswith("properties:v1:")


def test_property_cache_key_format() -> None:
    """Cache key should follow expected format."""
    filters = {"city": "Mumbai"}
    key = PropertyCacheManager.generate_cache_key(filters, user_id=5, page=3, limit=10)

    # Format: properties:v1:{hash}:u{user_id}:p{page}:l{limit}
    assert key.startswith("properties:v1:")
    assert ":u5:" in key
    assert ":p3:" in key
    assert ":l10" in key


def test_property_cache_key_empty_filters() -> None:
    """Cache key should work with empty filters."""
    filters = {}
    key = PropertyCacheManager.generate_cache_key(filters, user_id=0, page=1, limit=20)

    assert key is not None
    assert isinstance(key, str)


def test_property_cache_key_none_values_in_filters() -> None:
    """Cache key should handle None values in filters."""
    filters_a = {"city": "Delhi", "locality": None}
    filters_b = {"city": "Delhi"}

    key_a = PropertyCacheManager.generate_cache_key(filters_a, user_id=0, page=1, limit=20)
    key_b = PropertyCacheManager.generate_cache_key(filters_b, user_id=0, page=1, limit=20)

    # Keys may differ because one has explicit None
    assert key_a is not None
    assert key_b is not None
