#!/usr/bin/env python3
"""
Populate app versions data into the database.
"""

import json
import sys
import os
from pathlib import Path

# Add parent directory to path to import app modules
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.models.core import AppVersion
import asyncio


async def load_app_versions(clear_existing: bool = False):
    """Load app versions from JSON file into database."""
    # Create async engine
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession)

    async with async_session() as session:
        # Clear existing data if requested
        if clear_existing:
            await session.execute("TRUNCATE TABLE app_versions RESTART IDENTITY CASCADE")
            await session.commit()
            print("Cleared existing app versions")

        # Load app versions data
        app_versions_path = Path(__file__).parent / "data" / "app_versions.json"
        with open(app_versions_path, "r") as f:
            app_versions_data = json.load(f)

        # Create app version records
        for version_data in app_versions_data:
            app_version = AppVersion(**version_data)
            session.add(app_version)

        await session.commit()
        print(f"Successfully loaded {len(app_versions_data)} app versions")

        # Print summary
        print("\nApp versions loaded:")
        for version_data in app_versions_data:
            print(f"- {version_data['app']} ({version_data['platform']}): {version_data['version']}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Load app versions data into database")
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing app versions before loading"
    )

    args = parser.parse_args()

    # Run the async function
    asyncio.run(load_app_versions(clear_existing=args.clear))