import asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine
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

            # Create the WKT string for the point
            # Note: GeoAlchemy2/PostGIS expect POINT(longitude latitude)
            location_wkt = f'SRID=4326;POINT({lon} {lat})'

            # Create and execute the update statement
            update_stmt = update(Property).where(Property.id == prop_id).values(location=location_wkt)

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
    # This script needs to be run in an environment where the app's settings are available.
    # For example, by running `python -m populate_data.backfill_locations` from the project root.

    # To run this script, you might need to adjust the Python path if running directly
    import sys
    import os
    # Add project root to path to allow imports like `from app.core.config import settings`
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

    asyncio.run(backfill_property_locations())
