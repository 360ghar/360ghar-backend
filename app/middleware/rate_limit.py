from typing import Dict, Optional, Callable
from datetime import datetime, timedelta
import time
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import hashlib
from app.core.cache import cache_manager
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

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
        if request.url.path in ["/health", "/", "/docs", "/redoc"]:
            return await call_next(request)
        
        # Get client identifier
        client_id = self.get_client_id(request)
        
        # Check rate limit
        if not await self.check_rate_limit(client_id, request.url.path):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(self.period)}
            )
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(self.calls)
        response.headers["X-RateLimit-Period"] = str(self.period)
        
        return response
    
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
            ip = request.client.host
        
        return f"ip:{ip}"
    
    async def check_rate_limit(self, client_id: str, path: str) -> bool:
        """Check if request is within rate limit"""
        # Create cache key
        key = f"rate_limit:{self.scope}:{client_id}:{path}"
        
        # Get current timestamp
        now = int(time.time())
        window_start = now - self.period
        
        # Get request history from cache
        history = await cache_manager.get(key) or []
        
        # Filter requests within current window
        history = [ts for ts in history if ts > window_start]
        
        # Check if limit exceeded
        if len(history) >= self.calls:
            logger.warning(f"Rate limit exceeded for {client_id} on {path}")
            return False
        
        # Add current request
        history.append(now)
        
        # Update cache
        await cache_manager.set(key, history, ttl=self.period)
        
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
        key = f"endpoint_limit:{endpoint}:{client_id}"
        
        count = await cache_manager.get(key) or 0
        
        if count >= self.calls:
            return False
        
        await cache_manager.set(key, count + 1, ttl=self.period)
        return True
