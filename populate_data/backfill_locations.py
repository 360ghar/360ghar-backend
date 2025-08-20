import asyncio
import os
import sys
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import create_async_engine

# Ensure project root is on sys.path when running this script directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.models.models import Property

async def backfill_property_locations():
    """
    Backfills the 'location' geography column for existing properties
    from their latitude and longitude values.
    """
    print("Starting backfill for property locations...")

    # Use the async database URL from settings
    engine = create_async_engine(settings.ASYNC_DATABASE_URL)

    async with engine.connect() as conn:
        # Select all properties that have lat/lon but no location
        select_stmt = select(Property.id, Property.latitude, Property.longitude).where(
            Property.location.is_(None),
            Property.latitude.isnot(None),
            Property.longitude.isnot(None)
        )

        properties_to_update = (await conn.execute(select_stmt)).fetchall()

        if not properties_to_update:
            print("No properties need location backfill. Exiting.")
            return

        print(f"Found {len(properties_to_update)} properties to backfill.")

        updated_count = 0
        for prop in properties_to_update:
            prop_id, lat, lon = prop

            # Create the EWKT string for the point (longitude, latitude)
            location_wkt = f'SRID=4326;POINT({lon} {lat})'

            # Update using PostGIS geography constructor for type safety
            update_stmt = (
                update(Property)
                .where(Property.id == prop_id)
                .values(location=func.ST_GeogFromText(location_wkt))
            )

            try:
                await conn.execute(update_stmt)
                updated_count += 1
                if updated_count % 100 == 0:
                    print(f"Updated {updated_count}/{len(properties_to_update)} properties...")
            except Exception as e:
                print(f"Error updating property {prop_id}: {e}")

        # Commit the transaction after all updates
        await conn.commit()

        print(f"Backfill complete. Updated {updated_count} properties.")

if __name__ == "__main__":
    asyncio.run(backfill_property_locations())
