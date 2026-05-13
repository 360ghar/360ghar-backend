import asyncio
import logging

import sentry_sdk
import sentry_sdk.integrations.fastapi
import sentry_sdk.integrations.sqlalchemy
import yaml  # type: ignore[import-untyped]
from dotenv import load_dotenv
from fastapi import HTTPException
from fastapi.responses import Response
from sentry_sdk.integrations.logging import LoggingIntegration
from sqlalchemy import text

from app.config import settings
from app.core.db_resilience import is_transient_db_error
from app.core.logging import get_logger, setup_logging
from app.core.utils import utc_now_iso
from app.factory import create_app

load_dotenv()

# Configure logging
setup_logging()
logger = get_logger(__name__)


def _sentry_before_send(event, hint):
    """Strip sensitive headers from Sentry event payloads."""
    if "request" in event and "headers" in event["request"]:
        headers = event["request"]["headers"]
        if isinstance(headers, dict):
            headers.pop("authorization", None)
            headers.pop("x-api-key", None)
    return event


# Initialize Sentry
if settings.SENTRY_DSN:
    _is_dev = settings.ENVIRONMENT == "development"
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        # Free tier: keep traces low to stay within quota (100K/mo)
        traces_sample_rate=(
            settings.SENTRY_TRACES_SAMPLE_RATE
            if settings.SENTRY_TRACES_SAMPLE_RATE is not None
            else (0.5 if _is_dev else 0.05)
        ),
        send_default_pii=False,
        release=f"360ghar-backend@{settings.APP_VERSION}",
        before_send=_sentry_before_send,
        integrations=[
            sentry_sdk.integrations.fastapi.FastApiIntegration(),
            sentry_sdk.integrations.sqlalchemy.SqlalchemyIntegration(),
            LoggingIntegration(
                level=logging.WARNING,
                event_level=None,
            ),
        ],
    )
    logger.info("Sentry initialized", extra={"environment": settings.ENVIRONMENT})
else:
    logger.warning("Sentry DSN not configured - error tracking disabled")

# Create app using factory
app = create_app()


@app.get("/")
async def root():
    return {
        "message": "360Ghar Real Estate Platform API",
        "version": settings.APP_VERSION,
        "docs": f"{settings.API_V1_STR}/docs",
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint with database connectivity.

    Uses a raw engine connection (not the session pool) with a short
    timeout so the health check never blocks on pool exhaustion.
    Retries once on transient PgBouncer errors (EDBHANDLEREXITED, etc.).
    Always returns 200 — the status field indicates healthy/degraded.
    """
    db_status = "unknown"

    try:
        from app.core.database import engine

        for _attempt in range(2):
            try:
                async with asyncio.timeout(5):
                    async with engine.connect() as conn:
                        await conn.execute(text("SELECT 1"))
                db_status = "connected"
                break
            except Exception as db_e:
                if _attempt == 0 and is_transient_db_error(db_e):
                    logger.warning(
                        "Transient DB error on health check; retrying: %s", db_e
                    )
                    continue
                logger.error("Database health check failed: %s", db_e)
                db_status = "disconnected"
    except Exception as e:
        logger.error("Health check DB probe failed unexpectedly: %s", e)
        db_status = "disconnected"

    overall_status = "healthy" if db_status == "connected" else "degraded"

    return {
        "status": overall_status,
        "database": db_status,
        **(
            {
                "database_url": (
                    settings.DATABASE_URL.split("@", 1)[1]
                    if "@" in settings.DATABASE_URL
                    else "configured"
                )
            }
            if settings.ENVIRONMENT != "production"
            else {}
        ),
        "timestamp": utc_now_iso(),
        "version": settings.APP_VERSION,
    }


@app.get("/config")
async def get_config():
    """Get app configuration (non-sensitive)"""
    return {
        "api_version": settings.API_V1_STR,
        "environment": settings.ENVIRONMENT,
        "database": "SQLAlchemy + PostgreSQL",
        "auth": "Supabase",
        "features": [
            "User Authentication",
            "Property Discovery",
            "Location-based Search",
            "Swipe Functionality",
            "Visit Scheduling",
            "Short-stay Bookings",
            "Analytics",
        ],
    }


@app.get(f"{settings.API_V1_STR}/openapi.yaml")
async def get_openapi_yaml():
    """Download OpenAPI specification as YAML file"""
    openapi_json = app.openapi()
    yaml_str = yaml.dump(openapi_json, default_flow_style=False, sort_keys=False)
    return Response(
        content=yaml_str,
        media_type="application/x-yaml",
        headers={
            "Content-Disposition": "attachment; filename=360ghar-openapi-spec.yaml"
        },
    )


@app.get("/debug-sentry")
async def trigger_sentry_error():
    """Trigger a test error for Sentry verification (dev only)."""
    if settings.ENVIRONMENT == "production":
        raise HTTPException(status_code=404)
    raise RuntimeError("Sentry test error - this is intentional")
