from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_delete_user_account_invalidates_auth_user_cache() -> None:
    from app.services.user import delete_user_account

    user = MagicMock()
    user.id = 42
    user.supabase_user_id = "auth-sub-abc"
    user.profile_image_url = None

    with patch(
        "app.services.user.admin_delete_user",
        new=AsyncMock(return_value=True),
    ), patch(
        "app.services.user.invalidate_auth_user",
        new=AsyncMock(),
    ) as invalidate:
        db = AsyncMock()
        # The unmapped-column lookup reads rows from db.execute(...).all(). None here.
        db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))
        await delete_user_account(db, user)

    invalidate.assert_awaited_once_with("auth-sub-abc")
    db.flush.assert_awaited()


@pytest.mark.asyncio
async def test_delete_user_account_skips_cache_invalidation_on_provider_failure() -> None:
    from app.core.exceptions import ServiceUnavailableException
    from app.services.user import delete_user_account

    user = MagicMock()
    user.id = 42
    user.supabase_user_id = "auth-sub-abc"

    with patch(
        "app.services.user.admin_delete_user",
        new=AsyncMock(
            return_value={
                "__auth_failure__": True,
                "reason": "provider_unreachable",
                "error": "down",
            }
        ),
    ), patch(
        "app.services.user.invalidate_auth_user",
        new=AsyncMock(),
    ) as invalidate:
        db = AsyncMock()
        with pytest.raises(ServiceUnavailableException):
            await delete_user_account(db, user)

    invalidate.assert_not_awaited()
