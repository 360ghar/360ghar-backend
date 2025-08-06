import json
import pickle
from typing import Optional, Any, Union
from datetime import timedelta
import redis.asyncio as redis
from functools import wraps
import hashlib
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

class CacheManager:
    """Redis cache manager for application caching"""
    
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.default_ttl = 300  # 5 minutes default
    
    async def connect(self):
        """Initialize Redis connection"""
        try:
            self.redis_client = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=False,
                max_connections=50
            )
            await self.redis_client.ping()
            logger.info("Redis cache connected successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis_client = None
    
    async def disconnect(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()
    
    def _make_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate cache key from prefix and arguments"""
        key_data = f"{prefix}:{':'.join(map(str, args))}"
        if kwargs:
            key_data += f":{json.dumps(kwargs, sort_keys=True)}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    async def get(
        self,
        key: str,
        deserialize: bool = True
    ) -> Optional[Any]:
        """Get value from cache"""
        if not self.redis_client:
            return None
        
        try:
            value = await self.redis_client.get(key)
            if value and deserialize:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return pickle.loads(value)
            return value
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        serialize: bool = True
    ) -> bool:
        """Set value in cache"""
        if not self.redis_client:
            return False
        
        try:
            if serialize:
                try:
                    value = json.dumps(value)
                except (TypeError, ValueError):
                    value = pickle.dumps(value)
            
            ttl = ttl or self.default_ttl
            await self.redis_client.setex(key, ttl, value)
            return True
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not self.redis_client:
            return False
        
        try:
            await self.redis_client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False
    
    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern"""
        if not self.redis_client:
            return 0
        
        try:
            keys = await self.redis_client.keys(pattern)
            if keys:
                return await self.redis_client.delete(*keys)
            return 0
        except Exception as e:
            logger.error(f"Cache delete pattern error: {e}")
            return 0
    
    async def invalidate_user_cache(self, user_id: int):
        """Invalidate all cache entries for a user"""
        patterns = [
            f"user:{user_id}:*",
            f"auth:token:*:{user_id}",
            f"properties:user:{user_id}:*"
        ]
        for pattern in patterns:
            await self.delete_pattern(pattern)

class PropertyCacheManager:
    """Specialized cache manager for property queries"""
    
    @staticmethod
    def generate_cache_key(filters: dict, user_id: int, page: int, limit: int) -> str:
        """Generate consistent cache key for property queries"""
        # Sort and serialize filters for consistent hashing
        filter_str = json.dumps(filters, sort_keys=True)
        filter_hash = hashlib.md5(filter_str.encode()).hexdigest()[:16]
        
        return f"properties:v1:{filter_hash}:u{user_id}:p{page}:l{limit}"
    
    @staticmethod
    async def invalidate_property_caches(property_id: int):
        """Invalidate all caches related to a property"""
        pattern = f"properties:*"
        await cache_manager.delete_pattern(pattern)
    
    @staticmethod
    async def get_cached_properties(filters: dict, user_id: int, page: int, limit: int):
        """Get cached property results"""
        cache_key = PropertyCacheManager.generate_cache_key(filters, user_id, page, limit)
        return await cache_manager.get(cache_key)
    
    @staticmethod
    async def cache_properties(filters: dict, user_id: int, page: int, limit: int, result: dict, ttl: int = 300):
        """Cache property results"""
        cache_key = PropertyCacheManager.generate_cache_key(filters, user_id, page, limit)
        await cache_manager.set(cache_key, result, ttl)

# Initialize global cache manager
cache_manager = CacheManager()

def cache_key_wrapper(
    prefix: str,
    ttl: int = 300,
    key_params: list = None
):
    """Decorator for caching function results"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Build cache key
            cache_key_parts = [prefix]
            
            if key_params:
                for param in key_params:
                    if param in kwargs:
                        cache_key_parts.append(str(kwargs[param]))
            else:
                # Use all args and kwargs for key
                cache_key_parts.extend(map(str, args))
                if kwargs:
                    cache_key_parts.append(
                        hashlib.md5(
                            json.dumps(kwargs, sort_keys=True).encode()
                        ).hexdigest()[:8]
                    )
            
            cache_key = ":".join(cache_key_parts)
            
            # Try to get from cache
            cached_value = await cache_manager.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit: {cache_key}")
                return cached_value
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Store in cache
            await cache_manager.set(cache_key, result, ttl)
            logger.debug(f"Cache set: {cache_key}")
            
            return result
        
        return wrapper
    return decorator