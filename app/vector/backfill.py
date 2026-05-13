from __future__ import annotations

import asyncio
from typing import Any

from app.core.logging import get_logger
from app.vector.sync import run_property_vector_sync

logger = get_logger(__name__)


async def _run_once() -> dict[str, Any]:
    return await run_property_vector_sync()


def main():
    stats = asyncio.run(_run_once())
    logger.info("Backfill run completed", extra=stats)


if __name__ == "__main__":
    main()

