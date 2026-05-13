"""Application lifespan wiring and startup job orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.config import settings
from app.core.cache import initialize_cache, shutdown_cache
from app.core.database import bg_engine, engine
from app.core.logging import get_logger

logger = get_logger(__name__)

LifespanFactory = Callable[[FastAPI], Any]


def create_lifespan(testing: bool, user_mcp_app: Any, admin_mcp_app: Any) -> LifespanFactory:
    """Create the FastAPI lifespan manager with existing startup semantics."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with user_mcp_app.lifespan(app):
            async with admin_mcp_app.lifespan(app):
                try:
                    if not testing:
                        await _initialize_cache()
                        _start_schedulers(app)
                except Exception as exc:
                    logger.error("Application startup failed: %s", exc)

                logger.info(
                    "API started",
                    extra={
                        "event": "startup",
                        "env": settings.ENVIRONMENT,
                        "version": settings.APP_VERSION,
                        "mcp_servers": ["/mcp", "/mcp-admin"],
                        "serverless": settings.SERVERLESS_ENABLED,
                    },
                )

                yield

                # ---- Graceful shutdown ----
                if not testing:
                    _shutdown_schedulers()
                    await _shutdown_ai_providers()
                    _shutdown_notification_executor()
                    await _shutdown_supabase_clients()
                    await _shutdown_cache()
                await engine.dispose()
                await bg_engine.dispose()
                logger.info("API shutdown", extra={"event": "shutdown"})

    return lifespan


async def _initialize_cache() -> None:
    try:
        await initialize_cache()
    except Exception as cache_e:
        logger.warning("Cache connection skipped/failed: %s", cache_e)


async def _shutdown_cache() -> None:
    try:
        await shutdown_cache()
    except Exception as cache_e:
        logger.warning("Cache disconnect skipped/failed: %s", cache_e)


def _start_schedulers(app: FastAPI) -> None:
    if settings.SERVERLESS_ENABLED:
        logger.info(
            "Serverless mode enabled — skipping in-process schedulers "
            "to allow scale-to-zero. Move cron work to Railway cron jobs."
        )
        return

    _start_auto_blog_publish_scheduler(app)
    _start_notification_scheduler(app)
    _start_vector_sync_scheduler(app)
    _start_data_hub_scheduler(app)


def _start_auto_blog_publish_scheduler(app: FastAPI) -> None:
    try:
        from app.services.blog_auto_publish_scheduler import (
            start_auto_blog_publish_scheduler,
        )

        start_auto_blog_publish_scheduler(app)
    except Exception as sched_blog_e:
        logger.error("Failed to start auto blog publish scheduler: %s", sched_blog_e, exc_info=True)


def _start_notification_scheduler(app: FastAPI) -> None:
    try:
        from app.services.notification_scheduler import start_notification_scheduler

        start_notification_scheduler(app)
    except Exception as sched_e:
        logger.error("Failed to start notification scheduler: %s", sched_e, exc_info=True)


def _start_vector_sync_scheduler(app: FastAPI) -> None:
    try:
        from app.services.vector_sync_scheduler import start_vector_sync_scheduler

        start_vector_sync_scheduler(app)
    except Exception as sched_vec_e:
        logger.error("Failed to start vector sync scheduler: %s", sched_vec_e, exc_info=True)


def _start_data_hub_scheduler(app: FastAPI) -> None:
    try:
        from app.services.data_hub_scheduler import start_data_hub_scheduler

        start_data_hub_scheduler(app)
    except Exception as sched_dh_e:
        logger.error("Failed to start data hub scheduler: %s", sched_dh_e, exc_info=True)


def _shutdown_schedulers() -> None:
    """Gracefully stop all APScheduler instances via their public shutdown APIs."""
    for mod_path in (
        "app.services.blog_auto_publish_scheduler",
        "app.services.notification_scheduler",
        "app.services.vector_sync_scheduler",
        "app.services.data_hub_scheduler",
    ):
        try:
            import importlib

            mod = importlib.import_module(mod_path)
            mod.shutdown_scheduler()
        except Exception as e:
            logger.warning("Failed to shutdown scheduler %s: %s", mod_path, e)


async def _shutdown_ai_providers() -> None:
    """Close cached AI provider HTTP clients."""
    try:
        from app.services.ai import close_all_providers
        await close_all_providers()
    except Exception as e:
        logger.warning("Failed to close AI providers: %s", e)


def _shutdown_notification_executor() -> None:
    """Shut down the notification thread pool."""
    try:
        from app.services.notifications.helpers import shutdown_executor
        shutdown_executor()
    except Exception as e:
        logger.warning("Failed to shutdown notification executor: %s", e)


async def _shutdown_supabase_clients() -> None:
    """Close Supabase sync and async HTTP clients."""
    try:
        from app.core.auth import close_supabase_clients
        await close_supabase_clients()
    except Exception as e:
        logger.warning("Failed to close Supabase clients: %s", e)
