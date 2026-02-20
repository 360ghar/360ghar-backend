from typing import Optional, List
from fastapi import Request, HTTPException, status, Header
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta
from app.core.config import settings
from app.core.cache import get_cache_manager
from app.core.logging import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware:
    """
    Pure ASGI middleware for logging all incoming requests, including MCP paths.

    Uses raw ASGI instead of BaseHTTPMiddleware to avoid issues with streaming responses.
    """

    def __init__(self, app: ASGIApp, prefix: str = ""):
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            method = scope.get("method", "?")
            path = scope.get("path", "?")
            query = scope.get("query_string", b"").decode("utf-8", errors="ignore")

            # Log every incoming request
            full_path = f"{self.prefix}{path}" if self.prefix else path
            logger.info(
                "Incoming request",
                extra={
                    "method": method,
                    "path": full_path,
                    "query": query[:100] if query else None,
                }
            )

        await self.app(scope, receive, send)

class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add unique request ID to each request for tracing"""

    async def dispatch(self, request: Request, call_next):
        # Skip for MCP paths (streaming incompatible with BaseHTTPMiddleware)
        if request.url.path.startswith("/mcp"):
            return await call_next(request)

        # Generate or use existing request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Store request ID in request state for logging
        request.state.request_id = request_id

        # Process request
        response = await call_next(request)

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses"""

    async def dispatch(self, request: Request, call_next):
        # Skip for MCP paths (streaming incompatible with BaseHTTPMiddleware)
        if request.url.path.startswith("/mcp"):
            return await call_next(request)

        response = await call_next(request)
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Only send HSTS on production HTTPS deployments.
        if settings.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # Content Security Policy
        if settings.ENVIRONMENT == "production":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "connect-src 'self' https://api.supabase.co"
            )
        
        return response

class APIKeyMiddleware(BaseHTTPMiddleware):
    """API key validation for external API access"""
    
    def __init__(self, app, required_paths: List[str] = None):
        super().__init__(app)
        self.required_paths = required_paths or []
    
    async def dispatch(self, request: Request, call_next):
        # Check if path requires API key
        if any(request.url.path.startswith(path) for path in self.required_paths):
            api_key = request.headers.get("X-API-Key")
            
            if not api_key:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="API key required"
                )
            
            if not await self.validate_api_key(api_key):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid API key"
                )
        
        return await call_next(request)
    
    async def validate_api_key(self, api_key: str) -> bool:
        """Validate API key against stored keys"""
        cache = get_cache_manager()

        # Check cache first
        cache_key = f"api_key:{api_key[:10]}"
        cached = await cache.get(cache_key)
        if cached is not None:
            return cached

        # In production, check against database
        # For now, check against environment variable
        valid = api_key in settings.VALID_API_KEYS.split(",")

        # Cache result
        await cache.set(cache_key, valid, ttl=300)

        return valid

class RequestSignatureValidator:
    """Validate request signatures for webhook security"""
    
    @staticmethod
    def generate_signature(
        secret: str,
        method: str,
        path: str,
        body: bytes,
        timestamp: str
    ) -> str:
        """Generate HMAC signature for request"""
        message = f"{method}:{path}:{body.decode('utf-8')}:{timestamp}"
        signature = hmac.new(
            secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    @staticmethod
    async def validate_request(
        request: Request,
        secret: str,
        max_age_seconds: int = 300
    ) -> bool:
        """Validate request signature and timestamp"""
        # Get signature and timestamp from headers
        signature = request.headers.get("X-Signature")
        timestamp = request.headers.get("X-Timestamp")
        
        if not signature or not timestamp:
            return False
        
        # Check timestamp age
        try:
            request_time = datetime.fromisoformat(timestamp)
            if (datetime.utcnow() - request_time).total_seconds() > max_age_seconds:
                logger.warning("Request timestamp too old")
                return False
        except ValueError:
            return False
        
        # Get request body
        body = await request.body()
        
        # Generate expected signature
        expected_signature = RequestSignatureValidator.generate_signature(
            secret,
            request.method,
            request.url.path,
            body,
            timestamp
        )
        
        # Compare signatures
        return hmac.compare_digest(signature, expected_signature)

class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """IP whitelist middleware for admin endpoints"""
    
    def __init__(self, app, whitelist: List[str] = None, paths: List[str] = None):
        super().__init__(app)
        self.whitelist = whitelist or []
        self.paths = paths or ["/admin"]
    
    async def dispatch(self, request: Request, call_next):
        # Check if path requires IP whitelisting
        if any(request.url.path.startswith(path) for path in self.paths):
            client_ip = self.get_client_ip(request)
            
            if client_ip not in self.whitelist:
                logger.warning(f"Unauthorized IP access attempt: {client_ip}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied"
                )
        
        return await call_next(request)
    
    def get_client_ip(self, request: Request) -> str:
        """Get real client IP address"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        return request.client.host if request.client else "unknown"
