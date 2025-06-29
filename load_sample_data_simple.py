#!/usr/bin/env python3
"""
Load Sample Data to Supabase Database

This script loads sample data for the 360Ghar real estate platform.
"""

import asyncio
import asyncpg
import json
import random
from datetime import datetime, timedelta
from faker import Faker
from app.core.config import settings

fake = Faker('en_IN')

# Sample data
INDIAN_CITIES = [
    {"city": "Mumbai", "state": "Maharashtra", "lat": 19.0760, "lng": 72.8777},
    {"city": "Delhi", "state": "Delhi", "lat": 28.7041, "lng": 77.1025},
    {"city": "Bangalore", "state": "Karnataka", "lat": 12.9716, "lng": 77.5946},
    {"city": "Hyderabad", "state": "Telangana", "lat": 17.3850, "lng": 78.4867},
    {"city": "Chennai", "state": "Tamil Nadu", "lat": 13.0827, "lng": 80.2707},
    {"city": "Pune", "state": "Maharashtra", "lat": 18.5204, "lng": 73.8567}
]

LOCALITIES = {
    "Mumbai": ["Bandra", "Andheri", "Powai", "Thane", "Malad"],
    "Delhi": ["Gurgaon", "Noida", "Dwarka", "Lajpat Nagar"],
    "Bangalore": ["Koramangala", "Indiranagar", "Whitefield"],
    "Hyderabad": ["Hitech City", "Gachibowli", "Jubilee Hills"],
    "Chennai": ["T Nagar", "Adyar", "Velachery"],
    "Pune": ["Koregaon Park", "Wakad", "Hinjewadi"]
}

AMENITIES = ["Swimming Pool", "Gym", "Parking", "Security", "Power Backup", "Lift"]

async def check_tables_exist(conn):
    """Check if tables exist, create them if not"""
    print("📋 Checking database tables...")
    
    # Check if tables exist
    tables = await conn.fetch("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name IN 
        ('users', 'locations', 'properties', 'relationship_managers')
    """)
    
    existing_tables = [table['table_name'] for table in tables]
    print(f"Existing tables: {existing_tables}")
    
    if len(existing_tables) < 4:
        print("⚠️  Some tables are missing. Creating basic tables...")
        
        # Create basic tables
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                id SERIAL PRIMARY KEY,
                name VARCHAR NOT NULL,
                city VARCHAR NOT NULL,
                state VARCHAR NOT NULL,
                country VARCHAR DEFAULT 'India',
                pincode VARCHAR,
                locality VARCHAR,
                full_address TEXT,
                latitude FLOAT,
                longitude FLOAT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR UNIQUE NOT NULL,
                phone VARCHAR,
                hashed_password VARCHAR NOT NULL,
                full_name VARCHAR,
                is_active BOOLEAN DEFAULT true,
                preferences JSONB,
                current_latitude VARCHAR,
                current_longitude VARCHAR,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS relationship_managers (
                id SERIAL PRIMARY KEY,
                name VARCHAR NOT NULL,
                email VARCHAR UNIQUE NOT NULL,
                phone VARCHAR NOT NULL,
                employee_id VARCHAR UNIQUE,
                total_visits_handled INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS properties (
                id SERIAL PRIMARY KEY,
                title VARCHAR NOT NULL,
                description TEXT,
                property_type VARCHAR NOT NULL,
                purpose VARCHAR NOT NULL,
                location_id INTEGER REFERENCES locations(id),
                base_price FLOAT NOT NULL,
                area_sqft FLOAT,
                bedrooms INTEGER,
                bathrooms INTEGER,
                amenities JSONB,
                main_image_url VARCHAR,
                is_available BOOLEAN DEFAULT true,
                view_count INTEGER DEFAULT 0,
                like_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_swipes (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                property_id INTEGER REFERENCES properties(id),
                is_liked BOOLEAN NOT NULL,
                swipe_timestamp TIMESTAMP DEFAULT NOW(),
                session_id VARCHAR
            );
        """)
        
        print("✅ Basic tables created")
    else:
        print("✅ All required tables exist")

async def load_locations(conn, num_locations=50):
    """Load sample locations"""
    print(f"📍 Loading {num_locations} locations...")
    
    for i in range(num_locations):
        city_data = random.choice(INDIAN_CITIES)
        city = city_data["city"]
        state = city_data["state"]
        
        lat_offset = random.uniform(-0.05, 0.05)
        lng_offset = random.uniform(-0.05, 0.05)
        latitude = city_data["lat"] + lat_offset
        longitude = city_data["lng"] + lng_offset
        
        locality = random.choice(LOCALITIES.get(city, ["Central Area"]))
        
        await conn.execute("""
            INSERT INTO locations (name, city, state, pincode, locality, full_address, latitude, longitude)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, 
        f"{locality}, {city}",
        city,
        state,
        fake.postcode(),
        locality,
        f"{fake.building_number()}, {fake.street_name()}, {locality}, {city}, {state}",
        latitude,
        longitude
        )
    
    print(f"✅ Loaded {num_locations} locations")

async def load_relationship_managers(conn, num_rms=5):
    """Load sample relationship managers"""
    print(f"👨‍💼 Loading {num_rms} relationship managers...")
    
    for i in range(num_rms):
        await conn.execute("""
            INSERT INTO relationship_managers (name, email, phone, employee_id)
            VALUES ($1, $2, $3, $4)
        """,
        fake.name(),
        fake.email(),
        fake.phone_number(),
        f"RM{1000 + i}"
        )
    
    print(f"✅ Loaded {num_rms} relationship managers")

async def load_users(conn, num_users=25):
    """Load sample users"""
    print(f"👥 Loading {num_users} users...")
    
    for i in range(num_users):
        preferences = {
            "property_type": random.sample(["house", "apartment", "builder_floor"], random.randint(1, 2)),
            "purpose": random.choice(["buy", "rent", "short_stay"]),
            "budget_min": random.randint(10, 50) * 100000,
            "budget_max": random.randint(51, 200) * 100000
        }
        
        city_data = random.choice(INDIAN_CITIES)
        
        await conn.execute("""
            INSERT INTO users (email, phone, hashed_password, full_name, preferences, 
                             current_latitude, current_longitude)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        fake.email(),
        fake.phone_number(),
        "$2b$12$dummy.hashed.password.for.testing.only",
        fake.name(),
        json.dumps(preferences),
        str(city_data["lat"] + random.uniform(-0.02, 0.02)),
        str(city_data["lng"] + random.uniform(-0.02, 0.02))
        )
    
    print(f"✅ Loaded {num_users} users")

async def load_properties(conn, num_properties=100):
    """Load sample properties"""
    print(f"🏠 Loading {num_properties} properties...")
    
    # Get location IDs
    location_ids = await conn.fetch("SELECT id FROM locations")
    location_ids = [row['id'] for row in location_ids]
    
    for i in range(num_properties):
        property_type = random.choice(["house", "apartment", "builder_floor", "room"])
        purpose = random.choice(["buy", "rent", "short_stay"])
        
        if purpose == "buy":
            base_price = random.randint(2500000, 15000000)  # 25L to 1.5Cr
        elif purpose == "rent":
            base_price = random.randint(15000, 150000)  # 15K to 1.5L
        else:  # short_stay
            base_price = random.randint(1500, 15000)  # 1.5K to 15K per day
        
        bedrooms = random.randint(1, 4)
        amenities_list = random.sample(AMENITIES, random.randint(3, 6))
        
        await conn.execute("""
            INSERT INTO properties (title, description, property_type, purpose, location_id,
                                  base_price, area_sqft, bedrooms, bathrooms, amenities,
                                  main_image_url, view_count, like_count)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """,
        f"{bedrooms}BHK {property_type.title()} in {random.choice(INDIAN_CITIES)['city']}",
        f"Beautiful {property_type} with modern amenities. Perfect for {purpose}.",
        property_type,
        purpose,
        random.choice(location_ids),
        base_price,
        random.randint(400, 2000),
        bedrooms,
        random.randint(1, bedrooms + 1),
        json.dumps(amenities_list),
        f"https://picsum.photos/800/600?random={i}",
        random.randint(0, 500),
        random.randint(0, 100)
        )
    
    print(f"✅ Loaded {num_properties} properties")

async def load_user_swipes(conn):
    """Load sample user swipes"""
    print("👆 Loading user swipes...")
    
    # Get user and property IDs
    users = await conn.fetch("SELECT id FROM users LIMIT 20")
    properties = await conn.fetch("SELECT id FROM properties LIMIT 50")
    
    user_ids = [u['id'] for u in users]
    property_ids = [p['id'] for p in properties]
    
    swipe_count = 0
    for user_id in user_ids:
        # Each user swipes on 10-20 properties
        num_swipes = random.randint(10, 20)
        swiped_properties = random.sample(property_ids, min(num_swipes, len(property_ids)))
        
        for property_id in swiped_properties:
            is_liked = random.choice([True, False, False])  # 33% like rate
            
            await conn.execute("""
                INSERT INTO user_swipes (user_id, property_id, is_liked, session_id)
                VALUES ($1, $2, $3, $4)
            """,
            user_id,
            property_id,
            is_liked,
            fake.uuid4()[:8]
            )
            swipe_count += 1
    
    print(f"✅ Loaded {swipe_count} user swipes")

async def update_property_stats(conn):
    """Update property like counts based on swipes"""
    print("📊 Updating property statistics...")
    
    await conn.execute("""
        UPDATE properties 
        SET like_count = (
            SELECT COUNT(*) 
            FROM user_swipes 
            WHERE user_swipes.property_id = properties.id 
            AND user_swipes.is_liked = true
        )
    """)
    
    print("✅ Property statistics updated")

async def main():
    """Main function to load all sample data"""
    print("🚀 Loading Sample Data for 360Ghar")
    print("=" * 50)
    
    try:
        # Disable statement caching for Supabase pooler compatibility
        conn = await asyncpg.connect(settings.DATABASE_URL, statement_cache_size=0)
        print("✅ Connected to Supabase database")
        
        # Check and create tables if needed
        await check_tables_exist(conn)
        
        # Load sample data
        await load_locations(conn, 50)
        await load_relationship_managers(conn, 5)
        await load_users(conn, 25)
        await load_properties(conn, 100)
        await load_user_swipes(conn)
        await update_property_stats(conn)
        
        await conn.close()
        
        print("\n" + "=" * 50)
        print("🎉 Sample data loading completed!")
        print("\nData Summary:")
        print("📍 50 Locations across major Indian cities")
        print("👥 25 Users with preferences")
        print("🏠 100 Properties (buy/rent/short-stay)")
        print("👆 User swipes and interactions")
        print("👨‍💼 5 Relationship managers")
        print("\n🚀 Ready to start the API server!")
        print("Run: python run.py")
        
    except Exception as e:
        print(f"❌ Error loading sample data: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())