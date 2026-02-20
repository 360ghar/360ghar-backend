from typing import Dict, Callable
from datetime import datetime, timedelta
import time
from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
import hashlib
from app.core.cache import get_cache_manager
from app.core.logging import get_logger

logger = get_logger(__name__)

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using sliding window algorithm"""
    
    def __init__(
        self,
        app,
        calls: int = 100,
        period: int = 60,
        scope: str = "global"
    ):
        super().__init__(app)
        self.calls = calls
        self.period = period
        self.scope = scope
    
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks
        if self._is_exempt_path(request.url.path):
            return await call_next(request)
        
        # Get client identifier
        client_id = self.get_client_id(request)
        
        # Check rate limit
        if not await self.check_rate_limit(client_id, request.url.path):
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "Retry-After": str(self.period),
                    "X-RateLimit-Limit": str(self.calls),
                    "X-RateLimit-Period": str(self.period),
                },
            )
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(self.calls)
        response.headers["X-RateLimit-Period"] = str(self.period)
        
        return response

    def _is_exempt_path(self, path: str) -> bool:
        """Return True for endpoints that should not be rate limited."""
        exempt_paths = {
            "/",
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/openapi.yaml",
        }
        if path in exempt_paths:
            return True

        # FastAPI docs are served under settings.API_V1_STR (e.g. /api/v1/docs)
        if path.endswith("/docs") or path.endswith("/redoc"):
            return True
        if path.endswith("/openapi.json") or path.endswith("/openapi.yaml"):
            return True

        # MCP endpoints use streaming which is incompatible with BaseHTTPMiddleware
        if path.startswith("/mcp"):
            return True

        return False
    
    def get_client_id(self, request: Request) -> str:
        """Get unique client identifier"""
        # Try to get authenticated user ID
        if hasattr(request.state, "user_id"):
            return f"user:{request.state.user_id}"
        
        # Fall back to IP address
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0]
        else:
            ip = request.client.host if request.client else "unknown"
        
        return f"ip:{ip}"
    
    async def check_rate_limit(self, client_id: str, path: str) -> bool:
        """Check if request is within rate limit"""
        cache = get_cache_manager()

        # If cache not available, use in-memory fallback
        if not cache.is_available():
            return await self._check_rate_limit_memory(client_id, path)

        # Create cache key
        key = f"rate_limit:{self.scope}:{client_id}:{path}"

        # Get current timestamp
        now = int(time.time())
        window_start = now - self.period

        # Get request history from cache
        history = await cache.get(key) or []

        # Filter requests within current window
        history = [ts for ts in history if ts > window_start]

        # Check if limit exceeded
        if len(history) >= self.calls:
            logger.warning(f"Rate limit exceeded for {client_id} on {path}")
            return False

        # Add current request
        history.append(now)

        # Update cache
        await cache.set(key, history, ttl=self.period)

        return True
    
    _memory_store: Dict[str, list] = {}
    
    async def _check_rate_limit_memory(self, client_id: str, path: str) -> bool:
        """In-memory fallback for rate limiting when Redis is unavailable"""
        key = f"{self.scope}:{client_id}:{path}"
        now = int(time.time())
        window_start = now - self.period
        
        # Clean up old entries
        if key in self._memory_store:
            self._memory_store[key] = [ts for ts in self._memory_store[key] if ts > window_start]
        else:
            self._memory_store[key] = []
        
        # Check limit
        if len(self._memory_store[key]) >= self.calls:
            logger.warning(f"Rate limit exceeded (memory) for {client_id} on {path}")
            return False
        
        # Add request
        self._memory_store[key].append(now)
        return True

class EndpointRateLimiter:
    """Decorator for endpoint-specific rate limiting"""
    
    def __init__(self, calls: int = 10, period: int = 60):
        self.calls = calls
        self.period = period
    
    def __call__(self, func: Callable) -> Callable:
        async def wrapper(request: Request, *args, **kwargs):
            client_id = self.get_client_id(request)
            endpoint = f"{request.method}:{request.url.path}"
            
            if not await self.check_rate_limit(client_id, endpoint):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Max {self.calls} calls per {self.period} seconds",
                    headers={"Retry-After": str(self.period)}
                )
            
            return await func(request, *args, **kwargs)
        
        return wrapper
    
    def get_client_id(self, request: Request) -> str:
        """Get client identifier from request"""
        if hasattr(request.state, "user"):
            return f"user:{request.state.user.id}"
        
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0]
        else:
            ip = request.client.host if request.client else "unknown"
        
        return f"ip:{ip}"
    
    async def check_rate_limit(self, client_id: str, endpoint: str) -> bool:
        """Check rate limit for specific endpoint"""
        cache = get_cache_manager()
        key = f"endpoint_limit:{endpoint}:{client_id}"

        count = await cache.get(key) or 0

        if count >= self.calls:
            return False

        await cache.set(key, count + 1, ttl=self.period)
        return True
