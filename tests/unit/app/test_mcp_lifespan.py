from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI

from app.infrastructure import lifespan as lifespan_module
from app.infrastructure import mcp as mcp_module
from app.infrastructure.lifespan import create_lifespan
from app.infrastructure.mcp import LazyMCPHTTPApp, build_mcp_http_apps


class _DisposableEngine:
    def __init__(self, events: list[str], name: str) -> None:
        self._events = events
        self._name = name

    async def dispose(self) -> None:
        self._events.append(f"dispose:{self._name}")


class _InnerMCPApp:
    def __init__(self, events: list[str], name: str) -> None:
        self._events = events
        self._name = name

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        self._events.append(f"call:{self._name}")

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        self._events.append(f"enter:{self._name}")
        try:
            yield
        finally:
            self._events.append(f"exit:{self._name}")


class _LifespanRequiredMCPApp:
    def __init__(self, events: list[str], name: str) -> None:
        self._events = events
        self._name = name
        self._initialized = False

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if not self._initialized:
            raise RuntimeError(
                "FastMCP's StreamableHTTPSessionManager task group was not initialized"
            )
        self._events.append(f"call:{self._name}:{scope['path']}")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        self._events.append(f"enter:{self._name}")
        self._initialized = True
        try:
            yield
        finally:
            self._initialized = False
            self._events.append(f"exit:{self._name}")


class _RouterOnlyMCPApp:
    def __init__(self, events: list[str], name: str) -> None:
        self._events = events
        self._name = name
        self.router = SimpleNamespace(lifespan_context=self._lifespan)

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        self._events.append(f"enter:{self._name}")
        try:
            yield
        finally:
            self._events.append(f"exit:{self._name}")


def test_build_mcp_http_apps_returns_lifespan_aware_wrappers() -> None:
    user_mcp_app, admin_mcp_app = build_mcp_http_apps()

    assert isinstance(user_mcp_app, LazyMCPHTTPApp)
    assert isinstance(admin_mcp_app, LazyMCPHTTPApp)
    assert callable(getattr(user_mcp_app, "lifespan", None))
    assert callable(getattr(admin_mcp_app, "lifespan", None))


@pytest.mark.asyncio
async def test_lazy_mcp_http_app_lifespan_enters_inner_app(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    def build_inner(server_name: str) -> _InnerMCPApp:
        return _InnerMCPApp(events, server_name)

    monkeypatch.setattr(mcp_module, "_build_mcp_http_app", build_inner)

    async with LazyMCPHTTPApp("user").lifespan(FastAPI()):
        assert events == ["enter:user"]

    assert events == ["enter:user", "exit:user"]


@pytest.mark.asyncio
async def test_parent_lifespan_initializes_lazy_mcp_app_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    user_mcp_app = LazyMCPHTTPApp("user")
    admin_mcp_app = LazyMCPHTTPApp("admin")

    def build_inner(server_name: str) -> _LifespanRequiredMCPApp:
        return _LifespanRequiredMCPApp(events, server_name)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        events.append(f"send:{message['type']}")

    monkeypatch.setattr(mcp_module, "_build_mcp_http_app", build_inner)
    monkeypatch.setattr(lifespan_module, "mark_engines_disposing", lambda: events.append("mark"))
    monkeypatch.setattr(lifespan_module, "engine", _DisposableEngine(events, "engine"))
    monkeypatch.setattr(lifespan_module, "bg_engine", _DisposableEngine(events, "bg_engine"))

    app_lifespan = create_lifespan(
        testing=True,
        user_mcp_app=user_mcp_app,
        admin_mcp_app=admin_mcp_app,
    )

    async with app_lifespan(FastAPI()):
        await user_mcp_app(
            {"type": "http", "method": "POST", "path": "/mcp", "headers": []},
            receive,
            send,
        )

    assert events == [
        "enter:user",
        "enter:admin",
        "call:user:/mcp",
        "send:http.response.start",
        "send:http.response.body",
        "mark",
        "dispose:engine",
        "dispose:bg_engine",
        "exit:admin",
        "exit:user",
    ]


@pytest.mark.asyncio
async def test_create_lifespan_supports_starlette_router_lifespan_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(lifespan_module, "mark_engines_disposing", lambda: events.append("mark"))
    monkeypatch.setattr(lifespan_module, "engine", _DisposableEngine(events, "engine"))
    monkeypatch.setattr(lifespan_module, "bg_engine", _DisposableEngine(events, "bg_engine"))

    app_lifespan = create_lifespan(
        testing=True,
        user_mcp_app=_RouterOnlyMCPApp(events, "user"),
        admin_mcp_app=_RouterOnlyMCPApp(events, "admin"),
    )

    async with app_lifespan(FastAPI()):
        assert events == ["enter:user", "enter:admin"]

    assert events == [
        "enter:user",
        "enter:admin",
        "mark",
        "dispose:engine",
        "dispose:bg_engine",
        "exit:admin",
        "exit:user",
    ]


@pytest.mark.asyncio
async def test_create_lifespan_rejects_mcp_app_without_lifespan() -> None:
    app_lifespan = create_lifespan(
        testing=True,
        user_mcp_app=object(),
        admin_mcp_app=object(),
    )

    with pytest.raises(TypeError, match="user MCP app must expose a lifespan context"):
        async with app_lifespan(FastAPI()):
            pass


def _patch_shutdown_hooks(
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
) -> None:
    async def noop_async(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(lifespan_module, "shutdown_scheduler", lambda: None)
    monkeypatch.setattr(lifespan_module, "_shutdown_ai_providers", noop_async)
    monkeypatch.setattr(lifespan_module, "_shutdown_shared_http_clients", noop_async)
    monkeypatch.setattr(lifespan_module, "close_all_http_clients", noop_async)
    monkeypatch.setattr(lifespan_module, "_shutdown_cache", noop_async)
    monkeypatch.setattr(lifespan_module, "_shutdown_notification_executor", lambda: None)
    monkeypatch.setattr(lifespan_module, "mark_engines_disposing", lambda: None)
    monkeypatch.setattr(lifespan_module, "engine", _DisposableEngine(events, "engine"))
    monkeypatch.setattr(lifespan_module, "bg_engine", _DisposableEngine(events, "bg_engine"))


@pytest.mark.asyncio
async def test_non_production_required_startup_failures_record_degraded_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def fail_database_ready() -> None:
        events.append("required:db")
        raise RuntimeError("db down")

    async def fail_migrations() -> None:
        events.append("optional:ddl")
        raise RuntimeError("ddl down")

    async def noop_async(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(lifespan_module.settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(lifespan_module, "_validate_deeplink_config", lambda: None)
    monkeypatch.setattr(lifespan_module, "_verify_database_ready", fail_database_ready)
    monkeypatch.setattr(lifespan_module, "_apply_pending_migrations", fail_migrations)
    monkeypatch.setattr(lifespan_module, "_initialize_cache", noop_async)
    monkeypatch.setattr(lifespan_module, "_prewarm_supabase_dns", noop_async)
    monkeypatch.setattr(lifespan_module, "_start_scheduler_jobs", noop_async)
    _patch_shutdown_hooks(monkeypatch, events)

    app = FastAPI()
    app_lifespan = create_lifespan(
        testing=False,
        user_mcp_app=_RouterOnlyMCPApp(events, "user"),
        admin_mcp_app=_RouterOnlyMCPApp(events, "admin"),
    )

    async with app_lifespan(app):
        events.append("yield")

    assert app.state.startup_degraded is True
    # Migrations are skipped when readiness already failed (avoid another
    # multi-second SQLAlchemy hang on the same pooler outage).
    assert app.state.startup_errors == [
        {"phase": "database_readiness", "error": "db down"},
    ]
    assert "required:db" in events
    assert "optional:ddl" not in events
    assert "yield" in events


@pytest.mark.asyncio
async def test_production_transient_db_readiness_degrades_instead_of_aborting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pooler pressure must not abort production boot (Railway /health)."""
    events: list[str] = []

    async def fail_database_ready() -> None:
        events.append("required:db")
        raise RuntimeError(
            "Database readiness check failed: (ECHECKOUTTIMEOUT) unable to "
            "check out connection from the pool after 60000ms in Transaction mode"
        )

    async def noop_async(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(lifespan_module.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(lifespan_module, "_validate_deeplink_config", lambda: None)
    monkeypatch.setattr(lifespan_module, "_verify_database_ready", fail_database_ready)
    monkeypatch.setattr(lifespan_module, "_apply_pending_migrations", noop_async)
    monkeypatch.setattr(lifespan_module, "_initialize_cache", noop_async)
    monkeypatch.setattr(lifespan_module, "_prewarm_supabase_dns", noop_async)
    monkeypatch.setattr(lifespan_module, "_start_scheduler_jobs", noop_async)
    _patch_shutdown_hooks(monkeypatch, events)

    app = FastAPI()
    app_lifespan = create_lifespan(
        testing=False,
        user_mcp_app=_RouterOnlyMCPApp(events, "user"),
        admin_mcp_app=_RouterOnlyMCPApp(events, "admin"),
    )

    async with app_lifespan(app):
        events.append("yield")

    assert "yield" in events
    assert app.state.startup_degraded is True
    assert app.state.startup_errors == [
        {
            "phase": "database_readiness",
            "error": (
                "Database readiness check failed: (ECHECKOUTTIMEOUT) unable to "
                "check out connection from the pool after 60000ms in Transaction mode"
            ),
        }
    ]


@pytest.mark.asyncio
async def test_production_non_transient_db_readiness_aborts_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def fail_database_ready() -> None:
        events.append("required:db")
        raise RuntimeError("password authentication failed for user \"postgres\"")

    async def optional_startup(app: FastAPI) -> None:
        events.append("optional")

    monkeypatch.setattr(lifespan_module.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(lifespan_module, "_validate_deeplink_config", lambda: None)
    monkeypatch.setattr(lifespan_module, "_verify_database_ready", fail_database_ready)
    monkeypatch.setattr(lifespan_module, "_run_optional_startup", optional_startup)

    app_lifespan = create_lifespan(
        testing=False,
        user_mcp_app=_RouterOnlyMCPApp(events, "user"),
        admin_mcp_app=_RouterOnlyMCPApp(events, "admin"),
    )

    with pytest.raises(RuntimeError, match="password authentication failed"):
        async with app_lifespan(FastAPI()):
            pass

    assert "optional" not in events
    assert events == ["enter:user", "enter:admin", "required:db", "exit:admin", "exit:user"]


@pytest.mark.asyncio
async def test_production_startup_migration_failure_does_not_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup DDL is best-effort and must not block serving traffic."""
    events: list[str] = []

    async def pass_database_ready() -> None:
        events.append("required:db")

    async def fail_migrations() -> None:
        events.append("optional:ddl")
        raise RuntimeError("ddl down")

    async def noop_async(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(lifespan_module.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(lifespan_module, "_validate_deeplink_config", lambda: None)
    monkeypatch.setattr(lifespan_module, "_verify_database_ready", pass_database_ready)
    monkeypatch.setattr(lifespan_module, "_apply_pending_migrations", fail_migrations)
    monkeypatch.setattr(lifespan_module, "_initialize_cache", noop_async)
    monkeypatch.setattr(lifespan_module, "_prewarm_supabase_dns", noop_async)
    monkeypatch.setattr(lifespan_module, "_start_scheduler_jobs", noop_async)
    _patch_shutdown_hooks(monkeypatch, events)

    app = FastAPI()
    app_lifespan = create_lifespan(
        testing=False,
        user_mcp_app=_RouterOnlyMCPApp(events, "user"),
        admin_mcp_app=_RouterOnlyMCPApp(events, "admin"),
    )

    async with app_lifespan(app):
        events.append("yield")

    assert "yield" in events
    assert app.state.startup_degraded is True
    assert app.state.startup_errors == [
        {"phase": "startup_migrations", "error": "ddl down"},
    ]


@pytest.mark.asyncio
async def test_verify_database_ready_retries_then_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Readiness exhausts short attempts and raises with the last error."""
    attempts = {"n": 0}

    async def always_fail() -> None:
        attempts["n"] += 1
        raise RuntimeError(
            "(ECHECKOUTTIMEOUT) unable to check out connection from the pool"
        )

    monkeypatch.setattr(lifespan_module, "_DB_READINESS_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(lifespan_module, "_DB_READINESS_ATTEMPT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(lifespan_module, "_DB_READINESS_TOTAL_BUDGET_S", 5.0)
    monkeypatch.setattr(lifespan_module, "_DB_READINESS_MAX_SLEEP_S", 0.0)
    monkeypatch.setattr(lifespan_module, "_raw_database_probe", always_fail)

    with pytest.raises(RuntimeError, match="Database readiness check failed"):
        await lifespan_module._verify_database_ready()

    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_verify_database_ready_fails_fast_on_non_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auth/config errors must not burn the full retry budget."""
    attempts = {"n": 0}

    async def auth_fail() -> None:
        attempts["n"] += 1
        raise RuntimeError('password authentication failed for user "postgres"')

    monkeypatch.setattr(lifespan_module, "_DB_READINESS_MAX_ATTEMPTS", 12)
    monkeypatch.setattr(lifespan_module, "_raw_database_probe", auth_fail)

    with pytest.raises(RuntimeError, match="password authentication failed"):
        await lifespan_module._verify_database_ready()

    assert attempts["n"] == 1


@pytest.mark.asyncio
async def test_verify_database_ready_respects_total_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung probe must not wait beyond the wall-clock readiness budget."""
    import time

    attempts = {"n": 0}

    async def hang_forever() -> None:
        attempts["n"] += 1
        await asyncio.sleep(120)

    monkeypatch.setattr(lifespan_module, "_DB_READINESS_MAX_ATTEMPTS", 12)
    monkeypatch.setattr(lifespan_module, "_DB_READINESS_ATTEMPT_TIMEOUT_S", 0.15)
    monkeypatch.setattr(lifespan_module, "_DB_READINESS_TOTAL_BUDGET_S", 0.4)
    monkeypatch.setattr(lifespan_module, "_DB_READINESS_MAX_SLEEP_S", 0.0)
    monkeypatch.setattr(lifespan_module, "_raw_database_probe", hang_forever)

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="Database readiness check failed"):
        await lifespan_module._verify_database_ready()
    elapsed = time.monotonic() - started

    # Budget 0.4s + one attempt timeout slack; must not approach Supavisor's 60s.
    assert elapsed < 1.5
    assert attempts["n"] >= 1
    assert attempts["n"] <= 4


@pytest.mark.asyncio
async def test_verify_database_ready_times_out_hung_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-attempt wait_for must surface as a transient readiness failure."""
    import time

    async def hang_once() -> None:
        await asyncio.sleep(120)

    monkeypatch.setattr(lifespan_module, "_DB_READINESS_MAX_ATTEMPTS", 1)
    monkeypatch.setattr(lifespan_module, "_DB_READINESS_ATTEMPT_TIMEOUT_S", 0.1)
    monkeypatch.setattr(lifespan_module, "_DB_READINESS_TOTAL_BUDGET_S", 1.0)
    monkeypatch.setattr(lifespan_module, "_DB_READINESS_MAX_SLEEP_S", 0.0)
    monkeypatch.setattr(lifespan_module, "_raw_database_probe", hang_once)

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="Database readiness check failed"):
        await lifespan_module._verify_database_ready()
    assert time.monotonic() - started < 1.0


def test_readiness_conninfo_forces_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lifespan_module.settings,
        "DATABASE_URL",
        "postgresql://u:p@db.pooler.supabase.com:6543/postgres?sslmode=require",
    )
    monkeypatch.setattr(lifespan_module, "_DB_READINESS_CONNECT_TIMEOUT_S", 4)
    conninfo = lifespan_module._readiness_conninfo()
    assert conninfo.startswith("postgresql://")
    assert "connect_timeout=4" in conninfo
    assert "sslmode=require" in conninfo
    assert "+psycopg" not in conninfo


@pytest.mark.asyncio
async def test_is_transient_readiness_failure_classifies_pooler_errors() -> None:
    wrapped = RuntimeError(
        "Database readiness check failed: (ECHECKOUTTIMEOUT) unable to "
        "check out connection from the pool"
    )
    wrapped.__cause__ = Exception(
        "(ECHECKOUTTIMEOUT) unable to check out connection from the pool"
    )
    assert lifespan_module._is_transient_readiness_failure(wrapped) is True
    assert (
        lifespan_module._is_transient_readiness_failure(
            RuntimeError("password authentication failed for user \"postgres\"")
        )
        is False
    )
    assert lifespan_module._is_transient_readiness_failure(TimeoutError()) is True
