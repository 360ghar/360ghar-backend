from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.api_v1.endpoints.data_hub import registry, rera
from app.config import settings
from app.schemas.pagination import CursorParams


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "kwargs", "expected_table"),
    [
        (
            rera.list_rera_projects,
            {"status": None, "q": None},
            "rera_projects",
        ),
        (
            registry.list_zoning,
            {"sector": None},
            "zoning_data",
        ),
        (
            registry.list_colony_approvals,
            {},
            "colony_approvals",
        ),
    ],
)
async def test_provenance_lists_keep_primary_key_ordering(
    endpoint, kwargs: dict, expected_table: str, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "HRERA_DATA_ENABLED", True)
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result

    await endpoint(
        **kwargs,
        page=CursorParams(cursor=None, limit=20, include_total=False),
        db=db,
    )

    statement = str(db.execute.await_args.args[0]).lower()
    assert f"order by {expected_table}.id" in statement
