from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.api.api_v1.endpoints.blog import list_posts
from app.core.exceptions import ServiceUnavailableException
from app.schemas.pagination import CursorParams


@pytest.mark.asyncio
async def test_list_posts_maps_supabase_max_clients_to_503() -> None:
    db = AsyncMock()

    with patch(
        "app.api.api_v1.endpoints.blog.list_posts_cached",
        new=AsyncMock(
            side_effect=SQLAlchemyError(
                "(psycopg.OperationalError) connection failed: FATAL: "
                "(EMAXCONNSESSION) max clients reached in session mode"
            )
        ),
    ):
        with pytest.raises(ServiceUnavailableException) as exc_info:
            await list_posts(
                q=None,
                categories=None,
                tags=None,
                status=None,
                page=CursorParams(cursor=None, limit=20, include_total=False),
                db=db,
                current_user=None,
            )

    assert exc_info.value.status_code == 503
    assert exc_info.value.details["error_code"] == "EMAXCONNSESSION"
