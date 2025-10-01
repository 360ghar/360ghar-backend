#!/usr/bin/env python3
"""Populate agents from populate_data/data/agents.json"""

import argparse
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.logging import setup_logging, get_logger
from populate_data.data_populators.agent_populator import AgentPopulator

setup_logging()
logger = get_logger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Populate agents from JSON")
    parser.add_argument(
        "--file",
        dest="file_path",
        default=None,
        help="Path to agents.json (defaults to populate_data/data/agents.json)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Maximum number of agents to create",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear JSON-defined agents and exit",
    )

    args = parser.parse_args()

    populator = AgentPopulator()

    try:
        if args.clear:
            await populator.clear_all(file_path=args.file_path)
            logger.info("Cleared agents successfully")
            return

        result = await populator.populate_from_json(
            count=args.count,
            file_path=args.file_path,
        )
        logger.info(
            f"Agent population complete. Created: {result['created']}, Skipped: {result['skipped']}"
        )
    except Exception as exc:
        logger.error(f"Agent population failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
