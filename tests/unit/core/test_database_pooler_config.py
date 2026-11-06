from __future__ import annotations

import logging

import pytest

from app.core.database import (
    _database_pool_budget,
    _database_url_host_port,
    _validate_database_pooler_config,
)


def test_database_url_host_port_parses_supabase_pooler() -> None:
    host, port = _database_url_host_port(
        "postgresql://postgres.ref:secret@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"
    )

    assert host == "aws-1-ap-northeast-1.pooler.supabase.com"
    assert port == 6543


def test_database_pool_budget_includes_main_and_background_capacity() -> None:
    assert _database_pool_budget(4, 0, 1, 0) == 5
    assert _database_pool_budget(10, 20, 3, 5) == 38


def test_production_null_pool_rejects_supabase_session_pooler() -> None:
    with pytest.raises(RuntimeError, match="transaction pooler"):
        _validate_database_pooler_config(
            database_url=(
                "postgresql://postgres.ref:secret@"
                "aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres"
            ),
            null_pool=True,
            environment="production",
            db_pool_size=4,
            db_max_overflow=0,
            db_bg_pool_size=1,
            db_bg_max_overflow=0,
        )


def test_null_pool_accepts_supabase_transaction_pooler() -> None:
    _validate_database_pooler_config(
        database_url=(
            "postgresql://postgres.ref:secret@"
            "aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres"
        ),
        null_pool=True,
        environment="production",
        db_pool_size=4,
        db_max_overflow=0,
        db_bg_pool_size=1,
        db_bg_max_overflow=0,
    )


def test_production_rejects_supabase_session_pooler_even_with_small_budget() -> None:
    with pytest.raises(RuntimeError, match="transaction pooler"):
        _validate_database_pooler_config(
            database_url=(
                "postgresql://postgres.ref:secret@"
                "aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres"
            ),
            null_pool=False,
            environment="production",
            db_pool_size=1,
            db_max_overflow=0,
            db_bg_pool_size=1,
            db_bg_max_overflow=0,
        )


def test_development_pooled_warns_oversized_session_pool_budget(caplog) -> None:
    caplog.set_level(logging.WARNING, logger="app.core.database")

    _validate_database_pooler_config(
        database_url=(
            "postgresql://postgres.ref:secret@"
            "aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres"
        ),
        null_pool=False,
        environment="development",
        db_pool_size=10,
        db_max_overflow=20,
        db_bg_pool_size=3,
        db_bg_max_overflow=5,
    )

    assert "client budget is too high" in caplog.text
