import time
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

logger = logging.getLogger(__name__)


class PerformanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        response = await call_next(request)

        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)

        # Single concise request line in DEBUG
        if settings.DEBUG:
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": getattr(response, "status_code", 0),
                    "ms": int(process_time * 1000),
                },
            )

        # Log slow requests regardless of DEBUG
        if process_time > 1.0:
            logger.warning(
                "slow_request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "ms": int(process_time * 1000),
                },
            )

        # Add performance metrics to response headers
        response.headers["X-Performance-Tier"] = self._get_performance_tier(process_time)

        return response

    def _get_performance_tier(self, process_time: float) -> str:
        """Categorize response time into performance tiers"""
        if process_time < 0.1:
            return "excellent"
        elif process_time < 0.5:
            return "good"
        elif process_time < 1.0:
            return "acceptable"
        else:
            return "slow"