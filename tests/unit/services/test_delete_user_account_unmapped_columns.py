"""Account deletion resets every users column the ORM does not map.

The test schema is built from the ORM, so it has no unmapped columns. Each test that needs
one adds it with ALTER TABLE inside the test transaction, which rolls back at the end.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.services.user import delete_user_account


async def _delete(db_session, user) -> None:
    with (
        patch("app.services.user.admin_delete_user", new=AsyncMock(return_value=True)),
        patch("app.services.user.invalidate_auth_user", new=AsyncMock()),
    ):
        await delete_user_account(db_session, user)


async def _row(db_session, user_id: int, *columns: str) -> tuple:
    result = await db_session.execute(
        text(f"SELECT {', '.join(columns)} FROM users WHERE id = :id"), {"id": user_id}
    )
    return tuple(result.one())


@pytest.mark.asyncio
async def test_schema_without_unmapped_columns_deletes_cleanly(db_session, test_user):
    await _delete(db_session, test_user)

    assert await _row(db_session, test_user.id, "email", "phone", "full_name", "is_active") == (
        None,
        None,
        None,
        False,
    )


@pytest.mark.asyncio
async def test_unmapped_columns_are_reset_and_other_users_are_untouched(
    db_session, test_user, test_user_2
):
    await db_session.execute(
        text(
            "ALTER TABLE users "
            "ADD COLUMN flatmates_smoking_drinking varchar, "
            "ADD COLUMN ghar360_onboarding_completed boolean NOT NULL DEFAULT false, "
            'ADD COLUMN "Odd Secret" text'
        )
    )
    await db_session.execute(
        text(
            "UPDATE users SET flatmates_smoking_drinking = 'neither', "
            "ghar360_onboarding_completed = true, \"Odd Secret\" = 'x'"
        )
    )
    columns = ("flatmates_smoking_drinking", "ghar360_onboarding_completed", '"Odd Secret"')

    await _delete(db_session, test_user)

    assert await _row(db_session, test_user.id, *columns) == (None, False, None)
    assert await _row(db_session, test_user_2.id, *columns) == ("neither", True, "x")


@pytest.mark.asyncio
async def test_not_null_column_without_default_is_left_and_logged(db_session, test_user, caplog):
    await db_session.execute(
        text(
            "ALTER TABLE users ADD COLUMN keeps_value integer NOT NULL DEFAULT 5, "
            "ADD COLUMN secret_note text"
        )
    )
    await db_session.execute(text("ALTER TABLE users ALTER COLUMN keeps_value DROP DEFAULT"))
    await db_session.execute(text("UPDATE users SET secret_note = 'x'"))

    with caplog.at_level(logging.WARNING):
        await _delete(db_session, test_user)

    # The deletion finishes, resets the nullable column, and names the one it cannot reset.
    assert await _row(db_session, test_user.id, "keeps_value", "secret_note", "email") == (
        5,
        None,
        None,
    )
    assert any("users.keeps_value" in record.getMessage() for record in caplog.records)
