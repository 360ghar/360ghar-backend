#!/usr/bin/env python3
"""
Clear all test data from the database

Usage:
    python populate_data/clear_all_data.py
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.logging import setup_logging, get_logger
from populate_data.load_comprehensive_data import DataLoader

# Configure logging
setup_logging()
logger = get_logger(__name__)

async def main():
    """Clear all test data"""
    logger.info("Starting data cleanup...")
    
    loader = DataLoader()
    
    try:
        await loader.clear_all_data()
        logger.info("All test data cleared successfully!")
        
    except Exception as e:
        logger.error(f"Data cleanup failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())