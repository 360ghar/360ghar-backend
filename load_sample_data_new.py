#!/usr/bin/env python3
"""
Load Sample Data for 360Ghar Application
This script loads comprehensive sample data including users, properties, interactions, visits, and bookings
"""

import json
import random
from datetime import datetime, timedelta
from faker import Faker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.models.base import Base
from app.models.user import User
from app.models.property import Property, PropertyImage
from app.models.user_interaction import UserSwipe, UserFavorite, UserSearchHistory
from app.models.visit import Visit, RelationshipManager
from app.models.booking import Booking

fake = Faker('en_IN')

# Create database session
engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Sample data constants
GURGAON_LAT = 28.446400
GURGAON_LNG = 77.011711

# Gurgaon localities
GURGAON_LOCALITIES = [
    "DLF Phase 1", "DLF Phase 2", "DLF Phase 3", "DLF Phase 4", "DLF Phase 5",
    "Sector 28", "Sector 29", "Sector 43", "Sector 45", "Sector 46",
    "Sohna Road", "Golf Course Road", "MG Road", "Cyber City", "Udyog Vihar",
    "Sushant Lok", "South City", "Ardee City", "Vatika City", "Nirvana Country",
    "Gurgaon One", "Raheja Atlantis", "The Close", "Palm Springs", "Malibu Town"
]

AMENITIES = [
    "Swimming Pool", "Gym", "Parking", "Security", "Power Backup", "Lift", "Garden",
    "Clubhouse", "Play Area", "CCTV", "Intercom", "Fire Safety", "Water Supply",
    "Waste Management", "Wi-Fi", "Air Conditioning", "Modular Kitchen", "Balcony",
    "Vastu Compliant", "Pet Friendly", "Visitor Parking", "Rainwater Harvesting"
]

PROPERTY_TYPES = ["house", "apartment", "builder_floor", "room"]
PURPOSES = ["buy", "rent", "short_stay"]
STATUSES = ["available", "sold", "rented", "under_offer"]

# URLs provided by user
VIRTUAL_TOUR_URL = "https://kuula.co/share/collection/71284?logo=-1&card=1&info=0&fs=1&vr=1&thumbs=3&alpha=0.71"
MAIN_IMAGE_URL = "https://www.nobroker.in/blog/wp-content/uploads/2023/11/Victory-Valley.jpg"
OTHER_IMAGE_URL = "https://preview.redd.it/tallest-building-in-gurgaon-v0-z90z4alcfn0b1.jpg"

def create_tables_if_not_exist():
    """Create all tables if they don't exist"""
    print("Creating tables if they don't exist...")
    try:
        Base.metadata.create_all(bind=engine)
        print("✅ Tables created successfully")
    except Exception as e:
        print(f"⚠️  Error creating tables: {e}")

def clear_existing_data(db):
    """Clear existing data from all tables"""
    print("Clearing existing data...")
    try:
        db.query(Booking).delete()
        db.query(Visit).delete()
        db.query(UserSearchHistory).delete()
        db.query(UserFavorite).delete()
        db.query(UserSwipe).delete()
        db.query(PropertyImage).delete()
        db.query(Property).delete()
        db.query(RelationshipManager).delete()
        db.query(User).delete()
        db.commit()
        print("✅ Cleared existing data")
    except Exception as e:
        print(f"⚠️  Tables may not exist yet: {e}")
        db.rollback()

def create_main_user(db):
    """Create the main user with specific Supabase ID"""
    print("Creating main user...")
    
    main_user = User(
        supabase_user_id="3961aff5-00c8-4f34-9213-25649ecb55e3",
        email="saksham1991999@gmail.com",
        phone="+919876543210",
        full_name="Saksham Mittal",
        is_active=True,
        is_verified=True,
        current_latitude=str(GURGAON_LAT),
        current_longitude=str(GURGAON_LNG),
        preferences={
            "property_type": ["apartment", "house"],
            "purpose": "buy",
            "budget_min": 5000000,
            "budget_max": 20000000,
            "bedrooms_min": 2,
            "bedrooms_max": 4,
            "preferred_localities": ["DLF Phase 4", "Golf Course Road", "Sector 43"]
        },
        notification_settings={
            "email_notifications": True,
            "push_notifications": True,
            "sms_notifications": True
        }
    )
    db.add(main_user)
    db.commit()
    db.refresh(main_user)
    print(f"✅ Created main user: {main_user.email}")
    return main_user

def create_sample_users(db, num_users=20):
    """Create additional sample users"""
    print(f"Creating {num_users} additional users...")
    users = []
    
    for i in range(num_users):
        preferences = {
            "property_type": random.sample(PROPERTY_TYPES, random.randint(1, 2)),
            "purpose": random.choice(PURPOSES),
            "budget_min": random.randint(20, 100) * 100000,
            "budget_max": random.randint(101, 500) * 100000,
            "bedrooms_min": random.randint(1, 3),
            "bedrooms_max": random.randint(3, 5),
            "preferred_localities": random.sample(GURGAON_LOCALITIES, random.randint(2, 5))
        }
        
        user = User(
            supabase_user_id=fake.uuid4(),
            email=fake.email(),
            phone=fake.phone_number(),
            full_name=fake.name(),
            is_active=True,
            is_verified=random.choice([True, False]),
            current_latitude=str(GURGAON_LAT + random.uniform(-0.1, 0.1)),
            current_longitude=str(GURGAON_LNG + random.uniform(-0.1, 0.1)),
            preferences=preferences
        )
        db.add(user)
        users.append(user)
    
    db.commit()
    print(f"✅ Created {num_users} additional users")
    return users

def create_relationship_managers(db, num_rms=10):
    """Create relationship managers"""
    print(f"Creating {num_rms} relationship managers...")
    rms = []
    
    for i in range(num_rms):
        rm = RelationshipManager(
            name=fake.name(),
            email=fake.email(),
            phone=fake.phone_number(),
            whatsapp_number=fake.phone_number(),
            profile_image_url=f"https://i.pravatar.cc/150?img={i+1}",
            bio=fake.text(max_nb_chars=200),
            employee_id=f"RM{2024000 + i}",
            department="Customer Relations",
            experience_years=random.randint(1, 10),
            is_active=True,
            working_hours=json.dumps({
                "monday": "9:00 AM - 6:00 PM",
                "tuesday": "9:00 AM - 6:00 PM",
                "wednesday": "9:00 AM - 6:00 PM",
                "thursday": "9:00 AM - 6:00 PM",
                "friday": "9:00 AM - 6:00 PM",
                "saturday": "10:00 AM - 4:00 PM",
                "sunday": "Closed"
            }),
            total_visits_handled=random.randint(10, 200),
            customer_rating=str(round(random.uniform(4.0, 5.0), 1))
        )
        db.add(rm)
        rms.append(rm)
    
    db.commit()
    print(f"✅ Created {num_rms} relationship managers")
    return rms

def create_properties(db, num_properties=100):
    """Create properties around Gurgaon location"""
    print(f"Creating {num_properties} properties...")
    properties = []
    
    for i in range(num_properties):
        # Generate location within 10km radius of Gurgaon center
        lat_offset = random.uniform(-0.09, 0.09)  # ~10km radius
        lng_offset = random.uniform(-0.09, 0.09)
        latitude = GURGAON_LAT + lat_offset
        longitude = GURGAON_LNG + lng_offset
        
        locality = random.choice(GURGAON_LOCALITIES)
        property_type = random.choice(PROPERTY_TYPES)
        purpose = random.choice(PURPOSES)
        
        # Generate property details based on type
        if property_type == "room":
            bedrooms = 1
            bathrooms = 1
            area_sqft = random.randint(200, 500)
        elif property_type == "apartment":
            bedrooms = random.randint(1, 4)
            bathrooms = random.randint(1, 3)
            area_sqft = random.randint(650, 2500)
        elif property_type == "builder_floor":
            bedrooms = random.randint(2, 4)
            bathrooms = random.randint(2, 3)
            area_sqft = random.randint(1200, 3000)
        else:  # house
            bedrooms = random.randint(3, 6)
            bathrooms = random.randint(2, 5)
            area_sqft = random.randint(1800, 5000)
        
        # Generate pricing based on property type and area
        price_per_sqft_base = random.randint(8000, 15000)  # Gurgaon rates
        
        if purpose == "buy":
            base_price = area_sqft * price_per_sqft_base
            price_per_sqft = price_per_sqft_base
            monthly_rent = None
            daily_rate = None
            security_deposit = None
        elif purpose == "rent":
            monthly_rent = area_sqft * (price_per_sqft_base / 200) + random.randint(-5000, 10000)
            base_price = monthly_rent
            price_per_sqft = None
            daily_rate = None
            security_deposit = monthly_rent * 2
        else:  # short_stay
            daily_rate = area_sqft * (price_per_sqft_base / 2000) + random.randint(-500, 1000)
            base_price = daily_rate
            price_per_sqft = None
            monthly_rent = None
            security_deposit = daily_rate * 7
        
        # Generate amenities
        num_amenities = random.randint(5, 15)
        property_amenities = random.sample(AMENITIES, num_amenities)
        
        # Builder names for apartments
        builder_names = [
            "DLF Limited", "Unitech Group", "Ansal API", "Raheja Developers",
            "M3M India", "Godrej Properties", "Experion Developers", "Vatika Group",
            "Central Park", "Ireo", "Emaar India", "Shapoorji Pallonji"
        ]
        
        property = Property(
            title=f"{bedrooms}BHK {property_type.replace('_', ' ').title()} in {locality}",
            description=f"Beautiful {bedrooms}BHK {property_type.replace('_', ' ')} located in prime location of {locality}, Gurgaon. "
                       f"This property offers {area_sqft} sq.ft of living space with modern amenities and excellent connectivity.",
            property_type=property_type,
            purpose=purpose,
            status="available" if random.random() > 0.1 else random.choice(["sold", "rented"]),
            
            # Location data
            latitude=latitude,
            longitude=longitude,
            city="Gurgaon",
            state="Haryana",
            country="India",
            pincode=f"1220{random.randint(10, 99)}",
            locality=locality,
            sub_locality=fake.street_name(),
            landmark=random.choice([
                "Near Metro Station", "Near DLF CyberHub", "Near Ambience Mall",
                "Near Medanta Hospital", "Near Rapid Metro", "Near Golf Course",
                "Near HUDA City Centre", "Near Leisure Valley Park"
            ]),
            full_address=f"{fake.building_number()}, {fake.street_name()}, {locality}, Gurgaon, Haryana",
            area_type="residential",
            
            # Pricing
            base_price=base_price,
            price_per_sqft=price_per_sqft,
            monthly_rent=monthly_rent,
            daily_rate=daily_rate,
            security_deposit=security_deposit,
            maintenance_charges=random.randint(3000, 8000) if purpose != "buy" else None,
            
            # Property details
            area_sqft=area_sqft,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            balconies=random.randint(0, 3),
            parking_spaces=random.randint(0, 2),
            floor_number=random.randint(0, 20) if property_type != "house" else 0,
            total_floors=random.randint(5, 30) if property_type == "apartment" else random.randint(1, 4),
            age_of_property=random.randint(0, 15),
            
            # Short stay specific
            max_occupancy=bedrooms * 2 if purpose == "short_stay" else None,
            minimum_stay_days=random.choice([1, 2, 3, 7]) if purpose == "short_stay" else None,
            
            # Features
            amenities=property_amenities,
            features={
                "furnished": random.choice(["fully", "semi", "unfurnished"]),
                "facing": random.choice(["north", "south", "east", "west", "north-east", "north-west"]),
                "flooring": random.choice(["marble", "vitrified", "wooden", "granite"]),
                "corner_property": random.choice([True, False]),
                "gated_community": random.choice([True, False]),
                "pet_friendly": random.choice([True, False])
            },
            
            # Media
            main_image_url=MAIN_IMAGE_URL,
            virtual_tour_url=VIRTUAL_TOUR_URL if random.random() > 0.3 else None,
            
            # Availability
            is_available=True,
            available_from=datetime.now().strftime("%Y-%m-%d"),
            
            # SEO
            tags=[property_type, purpose, locality, f"{bedrooms}bhk", "gurgaon"],
            search_keywords=f"{bedrooms}bhk {property_type} {locality} gurgaon {purpose}",
            
            # Owner/Builder
            owner_name=fake.name(),
            owner_contact=fake.phone_number(),
            builder_name=random.choice(builder_names) if property_type == "apartment" else None,
            
            # Metrics
            view_count=random.randint(50, 2000),
            like_count=random.randint(5, 100),
            interest_count=random.randint(2, 50)
        )
        db.add(property)
        properties.append(property)
    
    db.commit()
    
    # Add property images
    print("Adding property images...")
    for property in properties:
        # Main image is already set, add additional images
        num_images = random.randint(3, 8)
        for j in range(num_images):
            image = PropertyImage(
                property_id=property.id,
                image_url=OTHER_IMAGE_URL if j == 0 else f"https://source.unsplash.com/800x600/?{random.choice(['apartment', 'house', 'interior', 'bedroom', 'kitchen', 'bathroom'])},{j}",
                caption=random.choice([
                    "Living Room", "Master Bedroom", "Kitchen", "Balcony View",
                    "Bathroom", "Guest Bedroom", "Dining Area", "Study Room",
                    "Building Exterior", "Common Area", "Parking Space"
                ]),
                display_order=j,
                is_main_image=(j == 0)
            )
            db.add(image)
    
    db.commit()
    print(f"✅ Created {num_properties} properties with images")
    return properties

def create_user_interactions(db, main_user, users, properties):
    """Create user interactions - swipes, favorites, search history"""
    print("Creating user interactions...")
    
    all_users = [main_user] + users
    
    # Create swipes
    swipe_count = 0
    for user in all_users:
        # Each user swipes on 20-50 properties
        num_swipes = random.randint(20, 50)
        swiped_properties = random.sample(properties, min(num_swipes, len(properties)))
        
        session_id = fake.uuid4()
        for property in swiped_properties:
            swipe = UserSwipe(
                user_id=user.id,
                property_id=property.id,
                is_liked=random.choice([True, False]),
                user_location_lat=user.current_latitude,
                user_location_lng=user.current_longitude,
                session_id=session_id
            )
            db.add(swipe)
            swipe_count += 1
    
    # Create favorites (from liked swipes)
    favorite_count = 0
    for user in all_users:
        # Get user's liked properties
        liked_swipes = db.query(UserSwipe).filter(
            UserSwipe.user_id == user.id,
            UserSwipe.is_liked == True
        ).limit(10).all()
        
        for swipe in liked_swipes:
            if random.random() > 0.5:  # 50% chance to favorite a liked property
                favorite = UserFavorite(
                    user_id=user.id,
                    property_id=swipe.property_id,
                    is_favorite=True,
                    notes=fake.sentence() if random.random() > 0.7 else None
                )
                db.add(favorite)
                favorite_count += 1
    
    # Create search history
    search_count = 0
    for user in all_users:
        # Each user has 5-15 searches
        num_searches = random.randint(5, 15)
        for _ in range(num_searches):
            search = UserSearchHistory(
                user_id=user.id,
                search_query=random.choice([
                    f"{random.randint(2,4)}bhk in {random.choice(GURGAON_LOCALITIES)}",
                    f"apartment under {random.randint(50, 200)} lakhs",
                    f"house for rent in gurgaon",
                    f"properties near metro station"
                ]),
                search_filters={
                    "property_type": random.choice(PROPERTY_TYPES),
                    "purpose": random.choice(PURPOSES),
                    "budget_min": random.randint(20, 100) * 100000,
                    "budget_max": random.randint(101, 500) * 100000,
                    "bedrooms": random.randint(1, 4)
                },
                search_location=random.choice(GURGAON_LOCALITIES),
                search_radius=random.randint(2, 10),
                results_count=random.randint(5, 50),
                user_location_lat=user.current_latitude,
                user_location_lng=user.current_longitude,
                search_type=random.choice(['discover', 'explore', 'direct_search']),
                session_id=fake.uuid4()
            )
            db.add(search)
            search_count += 1
    
    db.commit()
    print(f"✅ Created {swipe_count} swipes, {favorite_count} favorites, {search_count} searches")

def create_visits(db, main_user, users, properties, rms):
    """Create property visits"""
    print("Creating property visits...")
    
    all_users = [main_user] + users[:10]  # First 10 users have visits
    visit_count = 0
    
    for user in all_users:
        # Get user's favorited properties
        favorites = db.query(UserFavorite).filter(
            UserFavorite.user_id == user.id
        ).limit(5).all()
        
        for fav in favorites:
            if random.random() > 0.6:  # 40% chance to schedule visit
                scheduled_date = datetime.now() + timedelta(days=random.randint(1, 14))
                visit = Visit(
                    user_id=user.id,
                    property_id=fav.property_id,
                    relationship_manager_id=random.choice(rms).id,
                    scheduled_date=scheduled_date,
                    actual_date=scheduled_date if random.random() > 0.3 else None,
                    status=random.choice(["scheduled", "confirmed", "completed"]),
                    visitor_name=user.full_name,
                    visitor_phone=user.phone or fake.phone_number(),
                    visitor_email=user.email,
                    number_of_visitors=random.randint(1, 3),
                    preferred_time_slot=random.choice(["morning", "afternoon", "evening"]),
                    special_requirements=fake.sentence() if random.random() > 0.7 else None,
                    visit_notes="Property shown successfully. Client seemed interested." if random.random() > 0.5 else None,
                    visitor_feedback=fake.sentence() if random.random() > 0.6 else None,
                    interest_level=random.choice(["high", "medium", "low"]),
                    follow_up_required=random.choice([True, False])
                )
                db.add(visit)
                visit_count += 1
    
    db.commit()
    print(f"✅ Created {visit_count} property visits")

def create_bookings(db, main_user, users, properties):
    """Create bookings for short stay properties"""
    print("Creating bookings...")
    
    # Get short stay properties
    short_stay_properties = [p for p in properties if p.purpose == "short_stay"]
    if not short_stay_properties:
        print("No short stay properties available")
        return
    
    all_users = [main_user] + users[:5]  # First 5 users have bookings
    booking_count = 0
    
    for user in all_users:
        # Each user has 1-3 bookings
        num_bookings = random.randint(1, 3)
        booked_properties = random.sample(short_stay_properties, min(num_bookings, len(short_stay_properties)))
        
        for property in booked_properties:
            check_in = datetime.now() + timedelta(days=random.randint(7, 30))
            nights = random.randint(2, 7)
            check_out = check_in + timedelta(days=nights)
            guests = random.randint(1, property.max_occupancy or 4)
            
            base_amount = property.daily_rate * nights
            taxes = base_amount * 0.18  # 18% tax
            service_charges = base_amount * 0.05  # 5% service charge
            
            booking = Booking(
                user_id=user.id,
                property_id=property.id,
                booking_reference=f"BK{datetime.now().strftime('%Y%m%d')}{random.randint(1000, 9999)}",
                check_in_date=check_in,
                check_out_date=check_out,
                nights=nights,
                guests=guests,
                base_amount=base_amount,
                taxes_amount=taxes,
                service_charges=service_charges,
                discount_amount=0,
                total_amount=base_amount + taxes + service_charges,
                booking_status="confirmed" if random.random() > 0.2 else "pending",
                payment_status="paid" if random.random() > 0.3 else "pending",
                primary_guest_name=user.full_name,
                primary_guest_phone=user.phone or fake.phone_number(),
                primary_guest_email=user.email,
                guest_details={
                    "adults": guests,
                    "children": 0,
                    "infants": 0
                },
                special_requests=fake.sentence() if random.random() > 0.7 else None,
                payment_method=random.choice(["credit_card", "debit_card", "upi", "net_banking"]),
                transaction_id=fake.uuid4() if random.random() > 0.3 else None,
                payment_date=datetime.now() if random.random() > 0.3 else None
            )
            db.add(booking)
            booking_count += 1
    
    db.commit()
    print(f"✅ Created {booking_count} bookings")

def main():
    """Main function to load all sample data"""
    print("🚀 Loading comprehensive sample data for 360Ghar...")
    
    # Create tables first
    create_tables_if_not_exist()
    
    db = SessionLocal()
    
    try:
        # Clear existing data
        clear_existing_data(db)
        
        # Create users
        main_user = create_main_user(db)
        users = create_sample_users(db, 20)
        
        # Create relationship managers
        rms = create_relationship_managers(db, 10)
        
        # Create properties
        properties = create_properties(db, 100)
        
        # Create user interactions
        create_user_interactions(db, main_user, users, properties)
        
        # Create visits
        create_visits(db, main_user, users, properties, rms)
        
        # Create bookings
        create_bookings(db, main_user, users, properties)
        
        print("\n✅ Sample data loaded successfully!")
        print("📊 Summary:")
        print(f"   - 1 main user (saksham1991999@gmail.com)")
        print(f"   - 20 additional users")
        print(f"   - 10 relationship managers")
        print(f"   - 100 properties around Gurgaon")
        print(f"   - User interactions (swipes, favorites, searches)")
        print(f"   - Property visits scheduled")
        print(f"   - Bookings for short stay properties")
        
    except Exception as e:
        print(f"❌ Error loading sample data: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()