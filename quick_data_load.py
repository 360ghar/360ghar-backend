#!/usr/bin/env python3
"""
Quick Sample Data Loader

This script quickly loads essential sample data to test the API.
"""

import asyncio
import asyncpg
import json
import random
from faker import Faker
from app.core.config import settings

fake = Faker('en_IN')

async def load_essential_data():
    """Load minimal data to test the API"""
    print("🚀 Quick Loading Essential Data")
    print("=" * 40)
    
    try:
        conn = await asyncpg.connect(settings.DATABASE_URL, statement_cache_size=0)
        print("✅ Connected to database")
        
        # Check what tables exist
        existing_tables = await conn.fetch("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        table_names = [t['table_name'] for t in existing_tables]
        print(f"📋 Found tables: {table_names}")
        
        # Load locations (minimal)
        if 'locations' in table_names or 'Location' in table_names:
            print("📍 Loading locations...")
            try:
                # Check if locations table has data
                count = await conn.fetchval("SELECT COUNT(*) FROM locations")
                if count == 0:
                    cities = [
                        ("Mumbai", "Maharashtra", 19.0760, 72.8777),
                        ("Delhi", "Delhi", 28.7041, 77.1025),
                        ("Bangalore", "Karnataka", 12.9716, 77.5946)
                    ]
                    
                    for city, state, lat, lng in cities:
                        await conn.execute("""
                            INSERT INTO locations (name, city, state, country, latitude, longitude)
                            VALUES ($1, $2, $3, $4, $5, $6)
                        """, f"Central {city}", city, state, "India", lat, lng)
                    
                    print(f"✅ Added {len(cities)} locations")
                else:
                    print(f"✅ Found {count} existing locations")
            except Exception as e:
                print(f"⚠️  Locations: {e}")
        
        # Load users (minimal)
        if 'users' in table_names or 'User' in table_names:
            print("👥 Loading users...")
            try:
                count = await conn.fetchval("SELECT COUNT(*) FROM users")
                if count == 0:
                    for i in range(5):
                        await conn.execute("""
                            INSERT INTO users (email, hashed_password, full_name, is_active)
                            VALUES ($1, $2, $3, $4)
                        """, 
                        f"user{i+1}@360ghar.com",
                        "$2b$12$dummy.hashed.password.for.testing.only",
                        f"Test User {i+1}",
                        True
                        )
                    print("✅ Added 5 test users")
                else:
                    print(f"✅ Found {count} existing users")
            except Exception as e:
                print(f"⚠️  Users: {e}")
        
        # Load properties (minimal)
        if 'properties' in table_names or 'Property' in table_names:
            print("🏠 Loading properties...")
            try:
                count = await conn.fetchval("SELECT COUNT(*) FROM properties")
                if count == 0:
                    # Get a location ID
                    location_id = await conn.fetchval("SELECT id FROM locations LIMIT 1")
                    if location_id:
                        properties = [
                            ("2BHK Apartment in Mumbai", "apartment", "rent", 25000, 850, 2),
                            ("3BHK House in Delhi", "house", "buy", 5000000, 1200, 3),
                            ("1BHK Studio for Short Stay", "apartment", "short_stay", 2500, 500, 1),
                            ("4BHK Villa in Bangalore", "house", "buy", 12000000, 2500, 4),
                            ("2BHK Apartment for Rent", "apartment", "rent", 35000, 950, 2)
                        ]
                        
                        for title, prop_type, purpose, price, area, bedrooms in properties:
                            await conn.execute("""
                                INSERT INTO properties (title, property_type, purpose, location_id, 
                                                      base_price, area_sqft, bedrooms, is_available)
                                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                            """, title, prop_type, purpose, location_id, price, area, bedrooms, True)
                        
                        print(f"✅ Added {len(properties)} properties")
                    else:
                        print("⚠️  No locations found, skipping properties")
                else:
                    print(f"✅ Found {count} existing properties")
            except Exception as e:
                print(f"⚠️  Properties: {e}")
        
        await conn.close()
        
        print("\n" + "=" * 40)
        print("🎉 Essential data loaded!")
        print("🚀 Ready to start API: python run.py")
        return True
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

if __name__ == "__main__":
    asyncio.run(load_essential_data())