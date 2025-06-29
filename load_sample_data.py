import asyncio
import asyncpg
import json
import random
from datetime import datetime, timedelta
from faker import Faker
from app.core.config import settings

fake = Faker('en_IN')  # Use Indian locale for more relevant data

# Sample data for Indian real estate
INDIAN_CITIES = [
    {"city": "Mumbai", "state": "Maharashtra", "lat": 19.0760, "lng": 72.8777},
    {"city": "Delhi", "state": "Delhi", "lat": 28.7041, "lng": 77.1025},
    {"city": "Bangalore", "state": "Karnataka", "lat": 12.9716, "lng": 77.5946},
    {"city": "Hyderabad", "state": "Telangana", "lat": 17.3850, "lng": 78.4867},
    {"city": "Chennai", "state": "Tamil Nadu", "lat": 13.0827, "lng": 80.2707},
    {"city": "Kolkata", "state": "West Bengal", "lat": 22.5726, "lng": 88.3639},
    {"city": "Pune", "state": "Maharashtra", "lat": 18.5204, "lng": 73.8567},
    {"city": "Ahmedabad", "state": "Gujarat", "lat": 23.0225, "lng": 72.5714},
    {"city": "Jaipur", "state": "Rajasthan", "lat": 26.9124, "lng": 75.7873},
    {"city": "Surat", "state": "Gujarat", "lat": 21.1702, "lng": 72.8311}
]

LOCALITIES = {
    "Mumbai": ["Bandra", "Andheri", "Powai", "Thane", "Malad", "Borivali", "Goregaon", "Versova"],
    "Delhi": ["Gurgaon", "Noida", "Dwarka", "Lajpat Nagar", "Karol Bagh", "Connaught Place", "Saket"],
    "Bangalore": ["Koramangala", "Indiranagar", "Whitefield", "Electronic City", "BTM Layout", "HSR Layout"],
    "Hyderabad": ["Hitech City", "Gachibowli", "Jubilee Hills", "Banjara Hills", "Kondapur", "Madhapur"],
    "Chennai": ["T Nagar", "Adyar", "Velachery", "Anna Nagar", "Thoraipakkam", "OMR", "ECR"],
    "Kolkata": ["Salt Lake", "New Town", "Park Street", "Ballygunge", "Rajarhat", "Howrah"],
    "Pune": ["Koregaon Park", "Wakad", "Hinjewadi", "Aundh", "Viman Nagar", "Hadapsar"],
    "Ahmedabad": ["Satellite", "Vastrapur", "Bopal", "Gota", "Prahlad Nagar", "Maninagar"],
    "Jaipur": ["Malviya Nagar", "Vaishali Nagar", "Jagatpura", "Mansarovar", "C Scheme"],
    "Surat": ["Adajan", "Vesu", "Citylight", "Udhna", "Piplod", "Althan"]
}

AMENITIES = [
    "Swimming Pool", "Gym", "Parking", "Security", "Power Backup", "Lift", "Garden",
    "Clubhouse", "Play Area", "CCTV", "Intercom", "Fire Safety", "Water Supply",
    "Waste Management", "Wi-Fi", "Air Conditioning", "Modular Kitchen", "Balcony"
]

PROPERTY_TYPES = ["house", "apartment", "builder_floor", "room"]
PURPOSES = ["buy", "rent", "short_stay"]

async def create_sample_locations(conn, num_locations=100):
    """Create sample location data"""
    print(f"Creating {num_locations} sample locations...")
    
    locations = []
    for i in range(num_locations):
        city_data = random.choice(INDIAN_CITIES)
        city = city_data["city"]
        state = city_data["state"]
        
        # Add some randomness to coordinates (within city bounds)
        lat_offset = random.uniform(-0.1, 0.1)
        lng_offset = random.uniform(-0.1, 0.1)
        latitude = city_data["lat"] + lat_offset
        longitude = city_data["lng"] + lng_offset
        
        locality = random.choice(LOCALITIES.get(city, ["Central Area"]))
        
        location = {
            "name": f"{locality}, {city}",
            "city": city,
            "state": state,
            "country": "India",
            "pincode": fake.postcode(),
            "locality": locality,
            "sub_locality": fake.street_name(),
            "landmark": fake.company() + " " + random.choice(["Mall", "Hospital", "School", "Metro"]),
            "full_address": f"{fake.building_number()}, {fake.street_name()}, {locality}, {city}, {state}",
            "area_type": random.choice(["residential", "commercial", "mixed"]),
            "development_status": random.choice(["developed", "under_development", "planned"]),
            "coordinates": f"POINT({longitude} {latitude})"
        }
        locations.append(location)
    
    # Insert locations
    for location in locations:
        await conn.execute("""
            INSERT INTO locations (name, city, state, country, pincode, locality, sub_locality, 
                                 landmark, full_address, area_type, development_status, coordinates)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, ST_GeomFromText($12))
        """, location["name"], location["city"], location["state"], location["country"],
             location["pincode"], location["locality"], location["sub_locality"], 
             location["landmark"], location["full_address"], location["area_type"],
             location["development_status"], location["coordinates"])
    
    print(f"✅ Created {num_locations} locations")

async def create_sample_relationship_managers(conn, num_rms=10):
    """Create sample relationship managers"""
    print(f"Creating {num_rms} relationship managers...")
    
    for i in range(num_rms):
        await conn.execute("""
            INSERT INTO relationship_managers (name, email, phone, whatsapp_number, profile_image_url,
                                             bio, employee_id, department, experience_years, working_hours)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """, 
        fake.name(),
        fake.email(),
        fake.phone_number(),
        fake.phone_number(),
        f"https://randomuser.me/api/portraits/{'men' if random.choice([True, False]) else 'women'}/{random.randint(1, 99)}.jpg",
        f"Experienced real estate professional with {random.randint(2, 15)} years in the industry.",
        f"RM{1000 + i}",
        "Customer Relations",
        random.randint(1, 15),
        json.dumps({"monday": "9:00-18:00", "tuesday": "9:00-18:00", "wednesday": "9:00-18:00", 
                   "thursday": "9:00-18:00", "friday": "9:00-18:00", "saturday": "10:00-16:00"})
        )
    
    print(f"✅ Created {num_rms} relationship managers")

async def create_sample_users(conn, num_users=50):
    """Create sample users"""
    print(f"Creating {num_users} sample users...")
    
    for i in range(num_users):
        # Create user preferences
        preferences = {
            "property_type": random.sample(PROPERTY_TYPES, random.randint(1, 3)),
            "purpose": random.choice(PURPOSES),
            "budget_min": random.randint(10, 50) * 100000,  # 10L to 50L
            "budget_max": random.randint(51, 200) * 100000,  # 51L to 2Cr
            "bedrooms_min": random.randint(1, 2),
            "bedrooms_max": random.randint(3, 5),
            "location_preference": random.sample([city["city"] for city in INDIAN_CITIES], random.randint(1, 3))
        }
        
        city_data = random.choice(INDIAN_CITIES)
        lat_offset = random.uniform(-0.05, 0.05)
        lng_offset = random.uniform(-0.05, 0.05)
        
        await conn.execute("""
            INSERT INTO users (email, phone, hashed_password, full_name, date_of_birth,
                             is_active, is_verified, preferences, current_latitude, current_longitude,
                             notification_settings, privacy_settings)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """,
        fake.email(),
        fake.phone_number(),
        "$2b$12$dummy.hashed.password.for.testing.purposes.only",  # Dummy hash
        fake.name(),
        fake.date_of_birth(minimum_age=18, maximum_age=65),
        True,
        random.choice([True, False]),
        json.dumps(preferences),
        str(city_data["lat"] + lat_offset),
        str(city_data["lng"] + lng_offset),
        json.dumps({"email_notifications": True, "push_notifications": True, "sms_notifications": False}),
        json.dumps({"profile_visibility": "public", "location_sharing": True})
        )
    
    print(f"✅ Created {num_users} users")

async def create_sample_properties(conn, num_properties=200):
    """Create sample properties"""
    print(f"Creating {num_properties} sample properties...")
    
    # Get location IDs
    location_ids = await conn.fetch("SELECT id FROM locations")
    location_ids = [row['id'] for row in location_ids]
    
    for i in range(num_properties):
        property_type = random.choice(PROPERTY_TYPES)
        purpose = random.choice(PURPOSES)
        
        # Generate realistic pricing based on purpose and type
        if purpose == "buy":
            if property_type == "apartment":
                base_price = random.randint(2500000, 15000000)  # 25L to 1.5Cr
            elif property_type == "house":
                base_price = random.randint(5000000, 50000000)  # 50L to 5Cr
            else:
                base_price = random.randint(1500000, 8000000)   # 15L to 80L
            price_per_sqft = random.randint(3000, 12000)
            monthly_rent = None
            daily_rate = None
        elif purpose == "rent":
            monthly_rent = random.randint(15000, 150000)  # 15K to 1.5L
            base_price = monthly_rent
            price_per_sqft = None
            daily_rate = None
        else:  # short_stay
            daily_rate = random.randint(1500, 15000)  # 1.5K to 15K per day
            base_price = daily_rate
            price_per_sqft = None
            monthly_rent = None
        
        area_sqft = random.randint(400, 3000)
        bedrooms = random.randint(1, 5) if property_type != "room" else 1
        
        amenities_list = random.sample(AMENITIES, random.randint(5, 12))
        
        # Create realistic availability calendar for short stays
        calendar_data = None
        if purpose == "short_stay":
            calendar_data = {}
            for day in range(30):  # Next 30 days
                date = (datetime.now() + timedelta(days=day)).strftime('%Y-%m-%d')
                calendar_data[date] = {
                    "available": random.choice([True, True, True, False]),  # 75% availability
                    "price": daily_rate + random.randint(-500, 1000)
                }
        
        await conn.execute("""
            INSERT INTO properties (title, description, property_type, purpose, status, location_id,
                                  base_price, price_per_sqft, monthly_rent, daily_rate, security_deposit,
                                  maintenance_charges, area_sqft, bedrooms, bathrooms, balconies,
                                  parking_spaces, floor_number, total_floors, age_of_property,
                                  max_occupancy, minimum_stay_days, amenities, features, main_image_url,
                                  virtual_tour_url, is_available, available_from, calendar_data,
                                  tags, owner_name, owner_contact, builder_name, view_count, like_count)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28, $29, $30, $31, $32, $33, $34, $35)
        """,
        f"{bedrooms}BHK {property_type.title()} in {fake.city_suffix()}",
        f"Beautiful {property_type} with modern amenities and excellent connectivity. Perfect for {purpose}.",
        property_type,
        purpose,
        "available",
        random.choice(location_ids),
        base_price,
        price_per_sqft,
        monthly_rent,
        daily_rate,
        monthly_rent * 2 if monthly_rent else daily_rate * 7 if daily_rate else base_price * 0.1,
        random.randint(2000, 10000) if monthly_rent else None,
        area_sqft,
        bedrooms,
        random.randint(1, bedrooms + 1),
        random.randint(0, 3),
        random.randint(1, 3),
        random.randint(1, 20),
        random.randint(5, 50),
        random.randint(0, 15),
        bedrooms + 2 if purpose == "short_stay" else None,
        1 if purpose == "short_stay" else None,
        json.dumps(amenities_list),
        json.dumps({"furnished": random.choice(["fully", "semi", "unfurnished"]), 
                   "facing": random.choice(["north", "south", "east", "west"])}),
        f"https://picsum.photos/800/600?random={i}",
        f"https://360view.example.com/property/{i}" if random.choice([True, False]) else None,
        True,
        (datetime.now() + timedelta(days=random.randint(0, 90))).strftime('%Y-%m-%d'),
        json.dumps(calendar_data) if calendar_data else None,
        json.dumps([property_type, purpose, fake.city(), str(bedrooms) + "bhk"]),
        fake.name(),
        fake.phone_number(),
        fake.company() + " Constructions" if random.choice([True, False]) else None,
        random.randint(0, 1000),
        random.randint(0, 200)
        )
    
    print(f"✅ Created {num_properties} properties")

async def create_sample_property_images(conn):
    """Create sample property images"""
    print("Creating sample property images...")
    
    # Get all property IDs
    property_ids = await conn.fetch("SELECT id FROM properties")
    
    for prop in property_ids:
        property_id = prop['id']
        # Create 3-8 images per property
        num_images = random.randint(3, 8)
        
        for i in range(num_images):
            await conn.execute("""
                INSERT INTO property_images (property_id, image_url, caption, display_order, is_main_image)
                VALUES ($1, $2, $3, $4, $5)
            """,
            property_id,
            f"https://picsum.photos/800/600?random={property_id}{i}",
            random.choice(["Living Room", "Bedroom", "Kitchen", "Bathroom", "Balcony", "Exterior View"]),
            i,
            i == 0  # First image is main image
            )
    
    print(f"✅ Created property images")

async def create_sample_swipes_and_interactions(conn):
    """Create sample user swipes and interactions"""
    print("Creating sample user interactions...")
    
    # Get user and property IDs
    users = await conn.fetch("SELECT id FROM users")
    properties = await conn.fetch("SELECT id FROM properties")
    
    user_ids = [u['id'] for u in users]
    property_ids = [p['id'] for p in properties]
    
    # Create swipes
    for user_id in user_ids:
        # Each user swipes on 20-50 properties
        num_swipes = random.randint(20, 50)
        swiped_properties = random.sample(property_ids, min(num_swipes, len(property_ids)))
        
        for property_id in swiped_properties:
            is_liked = random.choice([True, False, False])  # 33% like rate
            
            await conn.execute("""
                INSERT INTO user_swipes (user_id, property_id, is_liked, swipe_timestamp,
                                       user_location_lat, user_location_lng, session_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            user_id,
            property_id,
            is_liked,
            fake.date_time_between(start_date='-30d', end_date='now'),
            str(random.uniform(12.0, 28.0)),  # India latitude range
            str(random.uniform(68.0, 97.0)),  # India longitude range
            fake.uuid4()[:8]
            )
        
        # Create search history
        for _ in range(random.randint(5, 15)):
            filters = {
                "property_type": random.sample(PROPERTY_TYPES, random.randint(1, 2)),
                "purpose": random.choice(PURPOSES),
                "price_min": random.randint(10, 50) * 100000,
                "price_max": random.randint(51, 200) * 100000
            }
            
            await conn.execute("""
                INSERT INTO user_search_history (user_id, search_query, search_filters, search_location,
                                                search_radius, results_count, user_location_lat,
                                                user_location_lng, search_type, session_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            user_id,
            random.choice(["2bhk apartment", "house for rent", "villa", "flat"]),
            json.dumps(filters),
            random.choice([city["city"] for city in INDIAN_CITIES]),
            random.randint(2, 20),
            random.randint(5, 100),
            str(random.uniform(12.0, 28.0)),
            str(random.uniform(68.0, 97.0)),
            random.choice(["discover", "explore", "direct_search"]),
            fake.uuid4()[:8]
            )
    
    print(f"✅ Created user interactions and search history")

async def create_sample_visits_and_bookings(conn):
    """Create sample visits and bookings"""
    print("Creating sample visits and bookings...")
    
    # Get IDs
    users = await conn.fetch("SELECT id FROM users")
    properties = await conn.fetch("SELECT id FROM properties WHERE purpose IN ('buy', 'rent')")
    short_stay_properties = await conn.fetch("SELECT id FROM properties WHERE purpose = 'short_stay'")
    rms = await conn.fetch("SELECT id FROM relationship_managers")
    
    user_ids = [u['id'] for u in users]
    property_ids = [p['id'] for p in properties]
    short_stay_ids = [p['id'] for p in short_stay_properties]
    rm_ids = [r['id'] for r in rms]
    
    # Create visits for buy/rent properties
    for _ in range(50):
        user_id = random.choice(user_ids)
        property_id = random.choice(property_ids)
        rm_id = random.choice(rm_ids)
        
        scheduled_date = fake.future_datetime(end_date='+30d')
        status = random.choice(["scheduled", "confirmed", "completed", "cancelled"])
        
        await conn.execute("""
            INSERT INTO visits (user_id, property_id, relationship_manager_id, scheduled_date,
                              status, visitor_name, visitor_phone, visitor_email, number_of_visitors,
                              preferred_time_slot, special_requirements, visit_notes, interest_level)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """,
        user_id, property_id, rm_id, scheduled_date, status,
        fake.name(), fake.phone_number(), fake.email(), random.randint(1, 4),
        random.choice(["morning", "afternoon", "evening"]),
        random.choice([None, "Need parking space", "Looking for pet-friendly", "Urgent requirement"]),
        "Property visited successfully" if status == "completed" else None,
        random.choice(["high", "medium", "low"]) if status == "completed" else None
        )
    
    # Create bookings for short-stay properties
    for _ in range(30):
        user_id = random.choice(user_ids)
        property_id = random.choice(short_stay_ids)
        
        check_in = fake.future_datetime(end_date='+60d')
        check_out = check_in + timedelta(days=random.randint(1, 7))
        nights = (check_out - check_in).days
        
        base_amount = random.randint(2000, 8000) * nights
        taxes = base_amount * 0.12
        service_charges = base_amount * 0.05
        total_amount = base_amount + taxes + service_charges
        
        booking_status = random.choice(["pending", "confirmed", "completed", "cancelled"])
        payment_status = "paid" if booking_status in ["confirmed", "completed"] else "pending"
        
        await conn.execute("""
            INSERT INTO bookings (user_id, property_id, booking_reference, check_in_date, check_out_date,
                                nights, guests, primary_guest_name, primary_guest_phone, primary_guest_email,
                                base_amount, taxes_amount, service_charges, total_amount, booking_status,
                                payment_status, guest_details)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
        """,
        user_id, property_id, f"BK{datetime.now().strftime('%Y%m%d')}{random.randint(1000, 9999)}",
        check_in, check_out, nights, random.randint(1, 4),
        fake.name(), fake.phone_number(), fake.email(),
        base_amount, taxes, service_charges, total_amount, booking_status, payment_status,
        json.dumps({"special_requests": random.choice([None, "Early check-in", "Late check-out", "Extra towels"])})
        )
    
    print(f"✅ Created visits and bookings")

async def main():
    """Main function to load all sample data"""
    print("🚀 Starting sample data loading for 360Ghar...")
    print("=" * 60)
    
    try:
        # Connect to database
        conn = await asyncpg.connect(settings.DATABASE_URL)
        print("✅ Connected to Supabase database")
        
        # Load sample data in order
        await create_sample_locations(conn, 100)
        await create_sample_relationship_managers(conn, 10)
        await create_sample_users(conn, 50)
        await create_sample_properties(conn, 200)
        await create_sample_property_images(conn)
        await create_sample_swipes_and_interactions(conn)
        await create_sample_visits_and_bookings(conn)
        
        await conn.close()
        
        print("\n" + "=" * 60)
        print("🎉 Sample data loading completed successfully!")
        print("\nSample data created:")
        print("📍 100 Locations across major Indian cities")
        print("👥 50 Users with preferences")
        print("🏠 200 Properties (buy/rent/short-stay)")
        print("🖼️  Property images for all properties")
        print("👆 User swipes and search history")
        print("📅 50 Property visits")
        print("🏨 30 Short-stay bookings")
        print("👨‍💼 10 Relationship managers")
        
    except Exception as e:
        print(f"❌ Error loading sample data: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())