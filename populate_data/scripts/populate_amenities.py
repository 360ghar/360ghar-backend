#!/usr/bin/env python3
"""Populate amenities from populate_data/data/amenities.json"""

import argparse
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.logging import setup_logging, get_logger
from populate_data.data_populators.amenity_populator import AmenityPopulator

setup_logging()
logger = get_logger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Populate amenities from JSON")
    parser.add_argument(
        "--file",
        dest="file_path",
        default=None,
        help="Path to amenities.json (defaults to populate_data/data/amenities.json)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Maximum number of amenities to create",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear JSON-defined amenities and exit",
    )

    args = parser.parse_args()

    populator = AmenityPopulator()

    try:
        if args.clear:
            await populator.clear_all(file_path=args.file_path)
            logger.info("Cleared amenities successfully")
            return

        result = await populator.populate_from_json(
            count=args.count,
            file_path=args.file_path,
        )
        logger.info(
            f"Amenity population complete. Created: {result['created']}, Skipped: {result['skipped']}"
        )
    except Exception as exc:
        logger.error(f"Amenity population failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
