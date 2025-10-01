#!/usr/bin/env python3
"""
Populate pages from populate_data/data/pages.json

Usage:
    python populate_data/populate_pages.py
    python populate_data/populate_pages.py --update     # Update existing pages
    python populate_data/populate_pages.py --clear      # Delete all pages
    python populate_data/populate_pages.py --file PATH  # Custom JSON file
"""

import argparse
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.logging import setup_logging, get_logger
from populate_data.data_populators.page_populator import PagePopulator


setup_logging()
logger = get_logger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Populate pages from JSON")
    parser.add_argument(
        "--file",
        dest="file_path",
        default=None,
        help="Path to pages.json (defaults to populate_data/data/pages.json)",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update existing pages if they already exist",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear all existing pages and exit",
    )

    args = parser.parse_args()

    populator = PagePopulator()

    try:
        if args.clear:
            await populator.clear_all()
            logger.info("Cleared all pages successfully")
            return

        created = await populator.populate(
            file_path=args.file_path,
            update_existing=args.update,
        )
        logger.info(
            f"Page population complete. Created: {created}{' (updates applied)' if args.update else ''}"
        )
    except Exception as e:
        logger.error(f"Page population failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

