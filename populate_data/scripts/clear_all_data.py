#!/usr/bin/env python3
"""
Comprehensive data clearing script for 360Ghar backend testing

This script safely clears all test data from the database in the correct dependency order.
It uses the new populator architecture to clear data from each entity type.

Usage:
    python populate_data/scripts/clear_all_data.py
    python populate_data/scripts/clear_all_data.py --confirm  # Skip confirmation prompt
"""

import asyncio
import argparse
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.logging import setup_logging, get_logger
from populate_data.data_populators.user_populator import UserPopulator
from populate_data.data_populators.agent_populator import AgentPopulator
from populate_data.data_populators.amenity_populator import AmenityPopulator
from populate_data.data_populators.property_populator import PropertyPopulator
from populate_data.data_populators.faq_populator import FAQPopulator
from populate_data.data_populators.page_populator import PagePopulator

# Configure logging
setup_logging()
logger = get_logger(__name__)


class DataClearer:
    """Coordinator for clearing all test data safely"""

    def __init__(self):
        # Initialize populators
        self.user_populator = UserPopulator()
        self.agent_populator = AgentPopulator()
        self.amenity_populator = AmenityPopulator()
        self.property_populator = PropertyPopulator()
        self.faq_populator = FAQPopulator()
        self.page_populator = PagePopulator()

    async def clear_all_data(self) -> dict:
        """
        Clear all test data in reverse dependency order

        Returns:
            Dict with deletion counts for each entity type
        """
        logger.info("Starting comprehensive data clearing...")

        results = {}

        try:
            # Clear in reverse dependency order to avoid foreign key constraint violations

            # 1. Properties (has foreign keys to users, amenities)
            logger.info("Clearing properties...")
            results["properties"] = await self.property_populator.clear_all()

            # 2. Users (has foreign keys to agents)
            logger.info("Clearing users...")
            results["users"] = await self.user_populator.clear_all()

            # 3. Agents (referenced by users)
            logger.info("Clearing agents...")
            results["agents"] = await self.agent_populator.clear_all()

            # 4. Amenities (referenced by property_amenities junction table)
            logger.info("Clearing amenities...")
            results["amenities"] = await self.amenity_populator.clear_all()

            # 5. FAQs (standalone)
            logger.info("Clearing FAQs...")
            results["faqs"] = await self.faq_populator.clear_all()

            # 6. Pages (standalone)
            logger.info("Clearing pages...")
            results["pages"] = await self.page_populator.clear_all()

            # Summary
            total_deleted = sum(results.values())
            logger.info("=" * 60)
            logger.info("DATA CLEARING COMPLETE")
            logger.info("=" * 60)
            logger.info(f"Total records deleted: {total_deleted}")
            logger.info("Breakdown:")
            for entity, count in results.items():
                logger.info(f"  - {entity}: {count}")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"Data clearing failed: {str(e)}")
            raise

        return results

    async def get_data_counts(self) -> dict:
        """
        Get current counts of records in each table

        Returns:
            Dict with current record counts
        """
        counts = {}

        try:
            async with self.user_populator.get_db_session() as session:
                # This is a simplified count - in a real implementation you'd count each table
                # For now, we'll just return a placeholder
                counts = {
                    "users": 0,  # Would need to implement actual counting
                    "agents": 0,
                    "amenities": 0,
                    "properties": 0,
                    "faqs": 0,
                    "pages": 0
                }
                logger.warning("Data counting not fully implemented - showing placeholder counts")

        except Exception as e:
            logger.error(f"Failed to get data counts: {str(e)}")

        return counts


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Clear all test data from 360Ghar database")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Skip confirmation prompt and proceed with clearing"
    )
    parser.add_argument(
        "--counts-only",
        action="store_true",
        help="Only show current data counts, don't clear anything"
    )

    args = parser.parse_args()

    clearer = DataClearer()

    try:
        if args.counts_only:
            # Just show current counts
            counts = await clearer.get_data_counts()
            logger.info("Current data counts:")
            for entity, count in counts.items():
                logger.info(f"  {entity}: {count}")
            return

        # Show warning and get confirmation
        if not args.confirm:
            print("\n" + "="*60)
            print("⚠️  WARNING: This will delete ALL test data from the database!")
            print("="*60)
            print("This includes:")
            print("  - All user accounts and profiles")
            print("  - All agent profiles")
            print("  - All properties and associated images")
            print("  - All amenities")
            print("  - All FAQs and pages")
            print()
            print("This action CANNOT be undone!")
            print()

            response = input("Are you sure you want to proceed? Type 'YES' to confirm: ")
            if response.strip() != "YES":
                logger.info("Data clearing cancelled by user")
                return

        # Proceed with clearing
        await clearer.clear_all_data()
        logger.info("✅ All test data cleared successfully!")

    except Exception as e:
        logger.error(f"❌ Data clearing failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())