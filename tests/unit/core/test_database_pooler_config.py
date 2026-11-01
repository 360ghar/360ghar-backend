from __future__ import annotations

import logging

import pytest

from app.core.database import (
    _database_pool_budget,
    _database_url_host_port,
    _validate_database_pooler_config,
)

TRANSACTION_POOLER_URL = (
    "postgresql://postgres.ref:secret@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"
)
SESSION_POOLER_URL = (
    "postgresql://postgres.ref:secret@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres"
)


def _validate(**overrides) -> None:
    kwargs: dict = {
        "database_url": TRANSACTION_POOLER_URL,
        "use_null_pool": False,
        "environment": "development",
        "replica_count": 1,
        "client_budget": 120,
        "db_pool_size": 8,
        "db_max_overflow": 2,
        "db_bg_pool_size": 2,
        "db_bg_max_overflow": 0,
    }
    kwargs.update(overrides)
    _validate_database_pooler_config(**kwargs)


def test_database_url_host_port_parses_supabase_pooler() -> None:
    host, port = _database_url_host_port(TRANSACTION_POOLER_URL)

    assert host == "aws-1-ap-northeast-1.pooler.supabase.com"
    assert port == 6543


def test_database_pool_budget_includes_main_and_background_capacity() -> None:
    assert _database_pool_budget(4, 0, 1, 0) == 5
    assert _database_pool_budget(10, 20, 3, 5) == 38


def test_production_rejects_supabase_session_pooler() -> None:
    with pytest.raises(RuntimeError, match="transaction pooler"):
        _validate(database_url=SESSION_POOLER_URL, environment="production")


def test_production_rejects_over_budget_pool() -> None:
    with pytest.raises(RuntimeError, match="DB_POOLER_CLIENT_BUDGET"):
        _validate(
            environment="production",
            replica_count=11,
            client_budget=120,
            db_pool_size=8,
            db_max_overflow=2,
            db_bg_pool_size=2,
            db_bg_max_overflow=0,
        )


def test_production_accepts_pool_within_budget() -> None:
    _validate(environment="production", replica_count=10, client_budget=120)


def test_development_warns_when_over_budget(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="app.core.database")

    _validate(environment="development", replica_count=11, client_budget=120)

    assert "exceeds DB_POOLER_CLIENT_BUDGET" in caplog.text


def test_null_pool_does_not_enforce_the_pool_budget(caplog) -> None:
    """NullPool has no client cap, so pool sizes are inert (only replicas matter)."""
    caplog.set_level(logging.WARNING, logger="app.core.database")

    _validate(
        use_null_pool=True,
        environment="production",
        replica_count=50,
        client_budget=1,
        db_pool_size=100,
        db_max_overflow=100,
        db_bg_pool_size=100,
        db_bg_max_overflow=100,
    )

    assert "DB_USE_NULL_POOL=true" in caplog.text
    assert "exceeds DB_POOLER_CLIENT_BUDGET" not in caplog.text


def test_development_non_session_pooler_warns_oversized_session_pool_budget(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="app.core.database")

    _validate(
        database_url=SESSION_POOLER_URL,
        environment="development",
        db_pool_size=10,
        db_max_overflow=20,
        db_bg_pool_size=3,
        db_bg_max_overflow=5,
    )

    assert "client budget is too high" in caplog.text
