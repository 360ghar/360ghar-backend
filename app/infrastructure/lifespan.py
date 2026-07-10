"""Application lifespan wiring and startup job orchestration."""

from __future__ import annotations

import asyncio
import socket
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import FastAPI

from app.config import settings
from app.core.cache import initialize_cache, shutdown_cache
from app.core.database import bg_engine, engine, mark_engines_disposing
from app.core.db_resilience import extract_db_error_code, is_transient_db_error
from app.core.http import close_all_clients as close_all_http_clients
from app.core.logging import get_logger
from app.infrastructure.scheduler import shutdown_scheduler, start_scheduler

logger = get_logger(__name__)

LifespanFactory = Callable[[FastAPI], Any]

# Readiness probe budget: hard wall-clock + short per-attempt caps so
# Supavisor's 60s ECHECKOUTTIMEOUT cannot burn Railway's healthcheck window.
# asyncio.wait_for alone does not abort a hung Supavisor queue wait; the
# probe uses sync libpq connect_timeout in a worker thread, and the loop
# exits as soon as the total budget is spent so lifespan can yield and
# /health becomes reachable (possibly degraded).
_DB_READINESS_MAX_ATTEMPTS = 3
_DB_READINESS_ATTEMPT_TIMEOUT_S = 5.0
_DB_READINESS_CONNECT_TIMEOUT_S = 4
_DB_READINESS_TOTAL_BUDGET_S = 25.0
_DB_READINESS_MAX_SLEEP_S = 2.0


def create_lifespan(testing: bool, user_mcp_app: Any, admin_mcp_app: Any) -> LifespanFactory:
    """Create the FastAPI lifespan manager with existing startup semantics."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Enter each MCP app's lifespan in *this* server async context. The
        # lifespan() context manager builds the concrete app and enters its
        # inner lifespan (starting the StreamableHTTPSessionManager task
        # group), so both enter and exit happen in the same context — avoiding
        # the "ValueError: was created in a different Context" that lazy
        # request-time init would otherwise cause.
        async with _mcp_app_lifespan(user_mcp_app, app, "user"):
            async with _mcp_app_lifespan(admin_mcp_app, app, "admin"):
                if not testing:
                    # Fail-fast config check runs OUTSIDE the degraded-mode
                    # try/except below: a placeholder Apple Team ID in
                    # production must abort startup, not be logged-and-ignored.
                    # It raises before the cache / DB initialize.
                    _validate_deeplink_config()
                _initialize_startup_state(app)
                if not testing:
                    await _run_required_startup(app)
                    await _run_optional_startup(app)

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

                try:
                    yield
                finally:
                    # Always free Supavisor client connections even if other
                    # teardown steps fail or hang until graceful-shutdown timeout.
                    try:
                        if not testing:
                            shutdown_scheduler()
                            await _shutdown_ai_providers()
                            await _shutdown_shared_http_clients()
                            await close_all_http_clients()
                            _shutdown_notification_executor()
                            await _shutdown_cache()
                    except Exception as shutdown_exc:
                        logger.warning(
                            "Non-DB shutdown step failed: %s",
                            shutdown_exc,
                            extra={"event": "shutdown_partial_failure"},
                        )
                    mark_engines_disposing()
                    try:
                        await engine.dispose()
                        await bg_engine.dispose()
                    except Exception as dispose_exc:
                        logger.error(
                            "Engine dispose failed: %s",
                            dispose_exc,
                            extra={"event": "engine_dispose_failed"},
                        )
                    logger.info("API shutdown", extra={"event": "shutdown"})

    return lifespan


def _initialize_startup_state(app: FastAPI) -> None:
    app.state.startup_degraded = False
    app.state.startup_errors = []


def _strict_required_startup() -> bool:
    return settings.ENVIRONMENT.lower() == "production"


async def _run_required_startup(app: FastAPI) -> None:
    """Run startup phases required for serving production traffic.

    Database readiness is required for *correct* traffic, but transient
    Supavisor/PgBouncer pressure (ECHECKOUTTIMEOUT, EDBHANDLEREXITED) must not
    abort the process: Railway's ``/health`` liveness probe never becomes
    reachable if lifespan raises, which turns a brief pooler blip into a
    deploy failure + restart storm that worsens pool saturation.

    Non-transient failures (auth, bad host, invalid URL) still abort production
    so misconfiguration is not silently served.
    """
    try:
        await _verify_database_ready()
    except Exception as exc:
        if _strict_required_startup() and not _is_transient_readiness_failure(exc):
            logger.error("Required startup phase failed (database_readiness): %s", exc)
            raise
        _record_startup_degradation(app, "database_readiness", exc)


async def _run_optional_startup(app: FastAPI) -> None:
    """Run best-effort startup phases that can degrade without aborting."""
    # Skip DDL when readiness already failed — SQLAlchemy first-connect can still
    # wait the full Supavisor 60s ECHECKOUTTIMEOUT and burn the healthcheck window.
    db_ready = not any(
        err.get("phase") == "database_readiness" for err in app.state.startup_errors
    )
    startup_steps: list[tuple[str, Callable[[], Any]]] = []
    if db_ready:
        startup_steps.append(("startup_migrations", _apply_pending_migrations))
    startup_steps.extend(
        (
            ("cache", _initialize_cache),
            ("supabase_dns_prewarm", _prewarm_supabase_dns),
            # _start_scheduler_jobs is async; calling it returns an awaitable.
            ("scheduler", lambda: _start_scheduler_jobs(app)),
        )
    )
    for phase, startup_step in startup_steps:
        try:
            await startup_step()
        except Exception as exc:
            _record_startup_degradation(app, phase, exc)


def _record_startup_degradation(app: FastAPI, phase: str, exc: Exception) -> None:
    app.state.startup_degraded = True
    app.state.startup_errors.append({"phase": phase, "error": str(exc)})
    logger.error(
        "Application startup degraded during %s: %s",
        phase,
        exc,
        extra={"event": "startup_degraded", "phase": phase},
    )


async def _start_scheduler_jobs(app: FastAPI) -> None:
    _register_scheduler_jobs(app)
    start_scheduler()


@asynccontextmanager
async def _mcp_app_lifespan(
    mcp_app: Any,
    parent_app: FastAPI,
    server_name: str,
) -> AsyncIterator[None]:
    """Enter a mounted MCP app lifespan using FastMCP's public ASGI contract."""
    lifespan_context = getattr(mcp_app, "lifespan", None)
    if lifespan_context is None:
        router = getattr(mcp_app, "router", None)
        lifespan_context = getattr(router, "lifespan_context", None)

    if lifespan_context is None:
        app_type = f"{type(mcp_app).__module__}.{type(mcp_app).__qualname__}"
        raise TypeError(
            f"{server_name} MCP app must expose a lifespan context; got {app_type}. "
            "Use app.infrastructure.mcp.build_mcp_http_apps() or a FastMCP http_app()."
        )

    async with lifespan_context(parent_app):
        yield


async def _apply_pending_migrations() -> None:
    """Run lightweight one-off DDL that cannot be applied via Supabase CLI migrations."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        for label, sql in (
            (
                "image_category: add floor_plan",
                "ALTER TYPE image_category ADD VALUE IF NOT EXISTS 'floor_plan'",
            ),
            (
                "leases: add termination_date",
                "ALTER TABLE public.leases ADD COLUMN IF NOT EXISTS termination_date date",
            ),
            (
                "leases: add termination_reason",
                "ALTER TABLE public.leases ADD COLUMN IF NOT EXISTS termination_reason text",
            ),
            (
                "tours: create visibility type",
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tour_visibility') THEN
                        CREATE TYPE tour_visibility AS ENUM ('private', 'unlisted', 'public');
                    END IF;
                END$$;
                """
            ),
            (
                "tours: add visibility column",
                "ALTER TABLE public.tours ADD COLUMN IF NOT EXISTS visibility public.tour_visibility NOT NULL DEFAULT 'private'"
            ),
            (
                "tours: migrate is_public to visibility",
                """
                UPDATE public.tours
                SET visibility = CASE
                    WHEN is_public = true THEN 'public'::public.tour_visibility
                    ELSE 'private'::public.tour_visibility
                END
                WHERE visibility = 'private' AND is_public = true
                """
            ),
            (
                "tours: create visibility index",
                "CREATE INDEX IF NOT EXISTS idx_tours_visibility ON public.tours(visibility)"
            ),
            (
                "tours: create status_visibility index",
                "CREATE INDEX IF NOT EXISTS idx_tours_status_visibility ON public.tours(status, visibility) WHERE deleted_at IS NULL"
            ),
        ):
            try:
                await conn.execute(text(sql))
                logger.info("Startup migration applied: %s", label)
            except Exception as exc:
                logger.warning("Startup migration skipped (%s): %s", label, exc)
                raise RuntimeError(f"Startup migration failed ({label})") from exc


async def _initialize_cache() -> None:
    try:
        await initialize_cache()
    except Exception as cache_e:
        logger.warning("Cache connection skipped/failed: %s", cache_e)


def _validate_deeplink_config() -> None:
    """Run the deep-link startup validator.

    In production (``DEEPLINK_FAIL_ON_PLACEHOLDER=True``) this raises if
    ``DEEPLINK_APPLE_TEAM_ID`` is the placeholder or otherwise malformed.
    In dev/CI it just logs a warning. Imported lazily so the module is
    only loaded when startup actually runs (avoids a top-level import of
    ``app.services.deeplinks`` from the lifespan module).
    """
    from app.services.deeplinks.validation import validate_deeplink_config

    validate_deeplink_config()


def _is_transient_readiness_failure(exc: BaseException) -> bool:
    """True when readiness failed due to pooler pressure or a short client timeout.

    Walks ``__cause__`` / ``__context__`` so a wrapping ``RuntimeError`` still
    classifies as transient when the root is ECHECKOUTTIMEOUT / EDBHANDLEREXITED.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, asyncio.TimeoutError)):
            return True
        if isinstance(current, Exception) and is_transient_db_error(current):
            return True
        message = str(current)
        if extract_db_error_code(Exception(message)):
            return True
        current = current.__cause__ or current.__context__
    return False


def _readiness_conninfo() -> str:
    """Build a libpq conninfo with a forced short ``connect_timeout``.

    Embedding the timeout in the URL (not only as a kwarg) ensures libpq
    always sees it even when callers pass other connection options.
    """
    url = settings.ASYNC_DATABASE_URL.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["connect_timeout"] = str(_DB_READINESS_CONNECT_TIMEOUT_S)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _sync_select_1(conninfo: str) -> None:
    """Blocking ``SELECT 1`` using sync psycopg + libpq ``connect_timeout``.

    Sync connect is preferred for readiness: libpq's connect_timeout aborts
    hung pooler waits more reliably than relying solely on asyncio
    cancellation of ``AsyncConnection.connect``.
    """
    import psycopg

    with psycopg.connect(
        conninfo,
        connect_timeout=_DB_READINESS_CONNECT_TIMEOUT_S,
        prepare_threshold=None,
        application_name="360ghar_readiness",
    ) as conn:
        conn.execute("SELECT 1")


async def _raw_database_probe() -> None:
    """Open a short-lived connection and run ``SELECT 1`` off the event loop."""
    await asyncio.to_thread(_sync_select_1, _readiness_conninfo())


async def _verify_database_ready() -> None:
    """Probe the database before accepting requests.

    Retries under a hard wall-clock budget so transient Supavisor pressure
    cannot monopolize startup. Non-transient failures (auth, bad host) fail
    immediately. Raises after the budget is exhausted; the required-startup
    wrapper degrades on transient failures instead of aborting production
    (which would make ``/health`` unreachable).
    """
    last_exc: Exception | None = None
    started = time.monotonic()
    deadline = started + _DB_READINESS_TOTAL_BUDGET_S

    for attempt in range(1, _DB_READINESS_MAX_ATTEMPTS + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

        attempt_started = time.monotonic()
        try:
            await asyncio.wait_for(
                _raw_database_probe(),
                timeout=min(_DB_READINESS_ATTEMPT_TIMEOUT_S, remaining),
            )
            elapsed_ms = int((time.monotonic() - attempt_started) * 1000)
            logger.info(
                "Database readiness check passed (attempt %d, elapsed_ms=%d)",
                attempt,
                elapsed_ms,
            )
            return
        except Exception as exc:
            last_exc = exc
            elapsed_ms = int((time.monotonic() - attempt_started) * 1000)
            error_code = extract_db_error_code(exc) or type(exc).__name__
            transient = _is_transient_readiness_failure(exc)

            # Auth/config errors will not recover by waiting — fail fast.
            if not transient:
                logger.error(
                    "Database readiness check failed with non-transient error "
                    "(attempt %d, code=%s, elapsed_ms=%d): %s",
                    attempt,
                    error_code,
                    elapsed_ms,
                    exc,
                )
                raise RuntimeError(
                    f"Database readiness check failed: {exc}"
                ) from exc

            remaining_after = deadline - time.monotonic()
            if attempt < _DB_READINESS_MAX_ATTEMPTS and remaining_after > 0:
                sleep_s = min(
                    0.5 * attempt,
                    _DB_READINESS_MAX_SLEEP_S,
                    remaining_after,
                )
                logger.warning(
                    "Database readiness check failed "
                    "(attempt %d/%d, code=%s, elapsed_ms=%d): %s",
                    attempt,
                    _DB_READINESS_MAX_ATTEMPTS,
                    error_code,
                    elapsed_ms,
                    exc,
                )
                if sleep_s > 0:
                    await asyncio.sleep(sleep_s)
            else:
                total_ms = int((time.monotonic() - started) * 1000)
                logger.error(
                    "Database readiness check failed after %d attempt(s) "
                    "(code=%s, total_elapsed_ms=%d): %s. "
                    "Startup cannot be marked fully ready.",
                    attempt,
                    error_code,
                    total_ms,
                    exc,
                )
                raise RuntimeError(
                    f"Database readiness check failed: {exc}"
                ) from exc

    total_ms = int((time.monotonic() - started) * 1000)
    logger.error(
        "Database readiness check exhausted budget after %dms (last code=%s): %s",
        total_ms,
        extract_db_error_code(last_exc) if last_exc else "none",
        last_exc,
    )
    raise RuntimeError(
        f"Database readiness check failed: {last_exc}"
    ) from last_exc


async def _prewarm_supabase_dns() -> None:
    """Resolve ``settings.SUPABASE_URL`` once at startup.

    Uses the running event loop's ``getaddrinfo`` (same resolver as
    httpx) so a misconfigured ``/etc/hosts`` or broken DNS surfaces in
    the startup log instead of only on the first authenticated request.
    Failures are logged at WARNING and do not block startup.
    """
    raw = settings.SUPABASE_URL
    if not raw:
        return
    host = raw.split("//", 1)[-1].split("/", 1)[0]
    if not host:
        return
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addrs = [info[4][0] for info in infos[:3]]
        logger.info(
            "Supabase DNS prewarm OK: %s -> %s",
            host,
            addrs,
            extra={"event": "supabase_dns_prewarm", "host": host, "addrs": addrs},
        )
    except (socket.gaierror, OSError) as exc:
        logger.warning(
            "Supabase DNS prewarm failed for %s: %s",
            host,
            exc,
            extra={"event": "supabase_dns_prewarm_failed", "host": host},
        )


async def _shutdown_cache() -> None:
    try:
        await shutdown_cache()
    except Exception as cache_e:
        logger.warning("Cache disconnect skipped/failed: %s", cache_e)


def _register_scheduler_jobs(app: FastAPI) -> None:
    """Register all scheduler jobs on the shared APScheduler, then start it."""
    if settings.SERVERLESS_ENABLED:
        logger.info(
            "Serverless mode enabled — skipping in-process schedulers "
            "to allow scale-to-zero. Move cron work to Railway cron jobs."
        )
        return

    _register_blog_publish_job(app)
    _register_notification_job(app)
    _register_vector_sync_job(app)
    _register_data_hub_jobs(app)


def _register_blog_publish_job(app: FastAPI) -> None:
    try:
        from app.services.blog_auto_publish_scheduler import start_auto_blog_publish_scheduler

        start_auto_blog_publish_scheduler(app)
    except Exception as sched_blog_e:
        logger.error("Failed to register blog publish scheduler: %s", sched_blog_e, exc_info=True)


def _register_notification_job(app: FastAPI) -> None:
    try:
        from app.services.notification_scheduler import start_notification_scheduler

        start_notification_scheduler(app)
    except Exception as sched_e:
        logger.error("Failed to register notification scheduler: %s", sched_e, exc_info=True)


def _register_vector_sync_job(app: FastAPI) -> None:
    try:
        from app.services.vector_sync_scheduler import start_vector_sync_scheduler

        start_vector_sync_scheduler(app)
    except Exception as sched_vec_e:
        logger.error("Failed to register vector sync scheduler: %s", sched_vec_e, exc_info=True)


def _register_data_hub_jobs(app: FastAPI) -> None:
    try:
        from app.services.data_hub_scheduler import start_data_hub_scheduler

        start_data_hub_scheduler(app)
    except Exception as sched_dh_e:
        logger.error("Failed to register data hub scheduler: %s", sched_dh_e, exc_info=True)


async def _shutdown_ai_providers() -> None:
    """Close cached AI provider HTTP clients."""
    try:
        from app.services.ai import close_all_providers
        await close_all_providers()
    except Exception as e:
        logger.warning("Failed to close AI providers: %s", e)


async def _shutdown_shared_http_clients() -> None:
    """Close reusable service HTTP clients (FCM, SMS)."""
    try:
        from app.services.notifications.fcm import close_fcm_client
        from app.services.sms import close_sms_client

        await close_fcm_client()
        await close_sms_client()
    except Exception as e:
        logger.warning("Failed to close shared HTTP clients: %s", e)


def _shutdown_notification_executor() -> None:
    """Shut down the notification thread pool."""
    try:
        from app.services.notifications.helpers import shutdown_executor
        shutdown_executor()
    except Exception as e:
        logger.warning("Failed to shutdown notification executor: %s", e)
