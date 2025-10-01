#!/usr/bin/env python3
"""Populate FAQs from populate_data/data/faqs.json"""

import argparse
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.logging import setup_logging, get_logger
from populate_data.data_populators.faq_populator import FAQPopulator


setup_logging()
logger = get_logger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Populate FAQs from JSON")
    parser.add_argument(
        "--file",
        dest="file_path",
        default=None,
        help="Path to faqs.json (defaults to populate_data/data/faqs.json)",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update existing FAQs if they already exist",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear JSON-defined FAQs and exit",
    )

    args = parser.parse_args()

    populator = FAQPopulator()

    try:
        if args.clear:
            await populator.clear_all(file_path=args.file_path)
            logger.info("Cleared FAQs successfully")
            return

        created = await populator.populate(
            file_path=args.file_path,
            update_existing=args.update,
        )
        logger.info(
            "FAQ population complete. Created: %s%s",
            created,
            " (updates applied)" if args.update else "",
        )
    except Exception as exc:
        logger.error(f"FAQ population failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
