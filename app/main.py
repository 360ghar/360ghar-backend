from __future__ import annotations

import asyncio
import logging

import sentry_sdk
import sentry_sdk.integrations.fastapi
import yaml
from dotenv import load_dotenv
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
    sentry_integrations = [
        sentry_sdk.integrations.fastapi.FastApiIntegration(),
        LoggingIntegration(
            level=logging.WARNING,
            event_level=None,
        ),
    ]
    if settings.SENTRY_ENABLE_SQLALCHEMY_TRACING:
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_integrations.append(SqlalchemyIntegration())

    traces_sample_rate = None
    if settings.SENTRY_ENABLE_TRACING:
        traces_sample_rate = (
            settings.SENTRY_TRACES_SAMPLE_RATE
            if settings.SENTRY_TRACES_SAMPLE_RATE is not None
            else 0.05
        )

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        release=f"360ghar-backend@{settings.APP_VERSION}",
        before_send=_sentry_before_send,
        integrations=sentry_integrations,
    )
    logger.info(
        "Sentry initialized",
        extra={
            "environment": settings.ENVIRONMENT,
            "tracing_enabled": settings.SENTRY_ENABLE_TRACING,
            "sqlalchemy_tracing_enabled": settings.SENTRY_ENABLE_SQLALCHEMY_TRACING,
        },
    )
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
    """Liveness check that does not touch downstream dependencies."""
    return {
        "status": "healthy",
        "timestamp": utc_now_iso(),
        "version": settings.APP_VERSION,
    }


@app.get("/ready")
async def readiness_check(response: Response):
    """Readiness check with database connectivity."""
    db_connected, db_status = await _probe_database_ready()
    if not db_connected:
        response.status_code = 503

    return {
        "status": "ready" if db_connected else "unready",
        "database": db_status,
        "timestamp": utc_now_iso(),
        "version": settings.APP_VERSION,
    }


async def _probe_database_ready() -> tuple[bool, str]:
    """Probe database connectivity for readiness checks."""
    try:
        from app.core.database import engine

        for _attempt in range(2):
            try:
                async with asyncio.timeout(5):
                    async with engine.connect() as conn:
                        await conn.execute(text("SELECT 1"))
                return True, "connected"
            except Exception as db_e:
                if _attempt == 0 and is_transient_db_error(db_e):
                    logger.warning(
                        "Transient DB error on readiness check; retrying: %s", db_e
                    )
                    continue
                logger.error("Database readiness check failed: %s", db_e)
                return False, "disconnected"
    except Exception as e:
        logger.error("Readiness DB probe failed unexpectedly: %s", e)
    return False, "disconnected"


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


if settings.sentry_test_endpoint_enabled:

    @app.get("/debug-sentry", include_in_schema=False)
    async def trigger_sentry_error():
        """Trigger a test error for Sentry verification when explicitly enabled."""
        raise RuntimeError("Sentry test error - this is intentional")
