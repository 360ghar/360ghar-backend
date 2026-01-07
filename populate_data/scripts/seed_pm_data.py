#!/usr/bin/env python3
"""
Property Management Data Seeding Script

Seeds the database with comprehensive mock data for PM features:
- Leases (with various statuses)
- Rent Charges & Payments
- Maintenance Requests
- Expenses
- Documents
- Inspections

Usage:
    python populate_data/scripts/seed_pm_data.py
    python populate_data/scripts/seed_pm_data.py --clear  # Clear PM data first
    python populate_data/scripts/seed_pm_data.py --clear-only  # Only clear, don't seed
"""

import asyncio
import argparse
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.logging import setup_logging, get_logger
from populate_data.data_populators.pm_data_populator import PMDataPopulator

# Configure logging
setup_logging()
logger = get_logger(__name__)


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Seed Property Management mock data into the database"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing PM data before seeding"
    )
    parser.add_argument(
        "--clear-only",
        action="store_true",
        help="Only clear PM data, don't seed new data"
    )
    parser.add_argument(
        "--max-leases",
        type=int,
        default=2,
        help="Maximum number of leases per property (default: 2)"
    )
    
    args = parser.parse_args()
    
    populator = PMDataPopulator()
    start_time = datetime.now()
    
    try:
        if args.clear or args.clear_only:
            logger.info("=" * 60)
            logger.info("CLEARING PM DATA")
            logger.info("=" * 60)
            
            cleared = await populator.clear_pm_data()
            
            logger.info("Cleared:")
            for entity, count in cleared.items():
                logger.info(f"  - {entity}: {count}")
            
            if args.clear_only:
                logger.info("Clear complete. Exiting.")
                return
        
        logger.info("=" * 60)
        logger.info("SEEDING PM DATA")
        logger.info("=" * 60)
        
        counts = await populator.populate_all(max_leases_per_property=args.max_leases)
        
        end_time = datetime.now()
        duration = end_time - start_time
        
        logger.info("=" * 60)
        logger.info("PM DATA SEEDING COMPLETE")
        logger.info("=" * 60)
        logger.info("Created:")
        for entity, count in counts.items():
            logger.info(f"  - {entity}: {count}")
        logger.info(f"Duration: {duration.total_seconds():.2f} seconds")
        logger.info("=" * 60)
        
        # Summary for testing
        logger.info("\nAPI ENDPOINTS TO TEST:")
        logger.info("-" * 40)
        logger.info("GET /api/v1/pm/properties/")
        logger.info("GET /api/v1/pm/leases/")
        logger.info("GET /api/v1/pm/rent/charges")
        logger.info("GET /api/v1/pm/rent/payments")
        logger.info("GET /api/v1/pm/maintenance/requests")
        logger.info("GET /api/v1/pm/expenses/")
        logger.info("GET /api/v1/pm/documents/")
        logger.info("GET /api/v1/pm/inspections/")
        logger.info("GET /api/v1/pm/dashboard/overview")
        logger.info("GET /api/v1/pm/dashboard/activity")
        
    except Exception as e:
        logger.error(f"PM data seeding failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
