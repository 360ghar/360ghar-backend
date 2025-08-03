"""
Base utilities and common functionality for data population
"""

import random
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from faker import Faker
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.property import PropertyType, PropertyPurpose, PropertyStatus
from app.models.booking import BookingStatus, PaymentStatus
from app.models.visit import VisitStatus

# User-provided constants
VIRTUAL_TOUR_URL = "https://kuula.co/share/collection/71284?logo=-1&card=1&info=0&fs=1&vr=1&thumbs=3&alpha=0.71"
MAIN_IMAGE_URL = "https://www.nobroker.in/blog/wp-content/uploads/2023/11/Victory-Valley.jpg"
OTHER_IMAGE_URL = "https://preview.redd.it/tallest-building-in-gurgaon-v0-z90z4alcfn0b1.jpg"

@dataclass
class LocationData:
    """Location-specific data and configurations"""
    name: str
    latitude: float
    longitude: float
    localities: List[str]
    price_per_sqft_range: Tuple[int, int]  # (min, max) in local currency
    currency: str
    popular_amenities: List[str]
    builder_names: List[str]
    landmarks: List[str]

# Location configurations
LOCATIONS = {
    "us": LocationData(
        name="San Francisco",
        latitude=37.785834,
        longitude=-122.406417,
        localities=[
            "SOMA", "Mission District", "Castro", "Nob Hill", "Pacific Heights",
            "Richmond", "Sunset", "Haight-Ashbury", "Marina", "Financial District",
            "Chinatown", "North Beach", "Presidio", "Potrero Hill", "Bernal Heights"
        ],
        price_per_sqft_range=(800, 1500),  # USD per sqft
        currency="USD",
        popular_amenities=[
            "Fitness Center", "Rooftop Deck", "Concierge", "Parking", "In-unit Laundry",
            "Doorman", "Pet Spa", "Business Center", "Storage", "Bike Storage"
        ],
        builder_names=[
            "Lennar", "KB Home", "D.R. Horton", "Pulte Group", "NVR Inc",
            "Toll Brothers", "Ryan Homes", "Meritage Homes", "Taylor Morrison"
        ],
        landmarks=[
            "Near BART Station", "Near Golden Gate Park", "Near Financial District",
            "Near Union Square", "Near Crissy Field", "Near Mission Dolores Park"
        ]
    ),
    "mumbai": LocationData(
        name="Mumbai",
        latitude=19.076,
        longitude=72.8777,
        localities=[
            "Bandra West", "Juhu", "Andheri West", "Powai", "Lower Parel",
            "Worli", "Malad West", "Goregaon West", "Versova", "Khar West",
            "Santa Cruz West", "Vile Parle West", "Borivali West", "Kandivali West", "Lokhandwala"
        ],
        price_per_sqft_range=(15000, 40000),  # INR per sqft
        currency="INR",
        popular_amenities=[
            "Swimming Pool", "Gym", "Club House", "Security", "Power Backup",
            "Lift", "Garden", "Children's Play Area", "CCTV", "Intercom"
        ],
        builder_names=[
            "Godrej Properties", "Lodha Group", "Oberoi Realty", "Hiranandani Group",
            "Kalpataru Limited", "Runwal Group", "Raheja Universal", "Sunteck Realty"
        ],
        landmarks=[
            "Near Mumbai Airport", "Near Bandra-Kurla Complex", "Near Powai Lake",
            "Near Phoenix Mills", "Near Palladium Mall", "Near Western Express Highway"
        ]
    ),
    "gurgaon": LocationData(
        name="Gurgaon",
        latitude=28.446400,
        longitude=77.011711,
        localities=[
            "DLF Phase 1", "DLF Phase 2", "DLF Phase 3", "DLF Phase 4", "DLF Phase 5",
            "Sector 28", "Sector 29", "Sector 43", "Sector 45", "Sector 46",
            "Sohna Road", "Golf Course Road", "MG Road", "Cyber City", "Udyog Vihar",
            "Sushant Lok", "South City", "Ardee City", "Vatika City", "Nirvana Country"
        ],
        price_per_sqft_range=(8000, 15000),  # INR per sqft
        currency="INR",
        popular_amenities=[
            "Swimming Pool", "Gym", "Parking", "Security", "Power Backup", "Lift", "Garden",
            "Clubhouse", "Play Area", "CCTV", "Intercom", "Fire Safety", "Water Supply"
        ],
        builder_names=[
            "DLF Limited", "Unitech Group", "Ansal API", "Raheja Developers",
            "M3M India", "Godrej Properties", "Experion Developers", "Vatika Group"
        ],
        landmarks=[
            "Near Metro Station", "Near DLF CyberHub", "Near Ambience Mall",
            "Near Medanta Hospital", "Near Rapid Metro", "Near Golf Course"
        ]
    )
}

@dataclass 
class DataConfig:
    """Configuration for data generation volumes and distributions"""
    users_count: int = 100
    properties_per_location: int = 700  # ~2100 total
    relationship_managers_count: int = 15
    swipes_per_user_range: Tuple[int, int] = (20, 80)
    favorites_percentage: float = 0.15  # 15% of liked swipes become favorites
    searches_per_user_range: Tuple[int, int] = (5, 25)
    visits_percentage: float = 0.3  # 30% of users schedule visits
    bookings_percentage: float = 0.2  # 20% of users make bookings

class DataPopulatorBase:
    """Base class for all data populators with common utilities"""
    
    def __init__(self, db_session: Session, config: DataConfig):
        self.db = db_session
        self.config = config
        self.fake = Faker()
        self.locations = LOCATIONS
        
        # Set up locale-specific fakers
        self.fake_us = Faker('en_US')
        self.fake_in = Faker('en_IN')
        
    def get_random_location_data(self, location_key: str) -> LocationData:
        """Get location data for a specific location"""
        return self.locations[location_key]
    
    def generate_coordinates_near(self, base_lat: float, base_lng: float, radius_km: float = 10) -> Tuple[float, float]:
        """Generate random coordinates within radius of base coordinates"""
        # Convert km to degrees (approximate)
        radius_deg = radius_km / 111.0  # 1 degree ≈ 111 km
        
        lat_offset = random.uniform(-radius_deg, radius_deg)
        lng_offset = random.uniform(-radius_deg, radius_deg)
        
        return (base_lat + lat_offset, base_lng + lng_offset)
    
    def generate_realistic_price(self, area_sqft: int, location: LocationData, property_type: PropertyType, 
                               purpose: PropertyPurpose) -> Dict[str, float]:
        """Generate realistic pricing based on location and property characteristics"""
        base_price_per_sqft = random.randint(*location.price_per_sqft_range)
        
        # Adjust based on property type
        type_multipliers = {
            PropertyType.ROOM: 0.7,
            PropertyType.APARTMENT: 1.0,
            PropertyType.BUILDER_FLOOR: 1.2,
            PropertyType.HOUSE: 1.5
        }
        
        adjusted_price_per_sqft = base_price_per_sqft * type_multipliers.get(property_type, 1.0)
        base_price = area_sqft * adjusted_price_per_sqft
        
        if purpose == PropertyPurpose.BUY:
            return {
                "base_price": base_price,
                "price_per_sqft": adjusted_price_per_sqft,
                "monthly_rent": None,
                "daily_rate": None,
                "security_deposit": None
            }
        elif purpose == PropertyPurpose.RENT:
            monthly_rent = base_price * random.uniform(0.003, 0.006)  # 0.3-0.6% of property value
            return {
                "base_price": monthly_rent,
                "price_per_sqft": None,
                "monthly_rent": monthly_rent,
                "daily_rate": None,
                "security_deposit": monthly_rent * random.randint(2, 6)
            }
        else:  # SHORT_STAY
            daily_rate = monthly_rent / 30 * random.uniform(1.5, 2.5) if 'monthly_rent' in locals() else base_price * 0.001
            return {
                "base_price": daily_rate,
                "price_per_sqft": None,
                "monthly_rent": None,
                "daily_rate": daily_rate,
                "security_deposit": daily_rate * random.randint(3, 10)
            }
    
    def generate_property_features(self, property_type: PropertyType, location: LocationData) -> Dict[str, Any]:
        """Generate realistic property features based on type and location"""
        features = {}
        
        # Basic features
        features["furnished"] = random.choice(["fully", "semi", "unfurnished"])
        features["facing"] = random.choice(["north", "south", "east", "west", "north-east", "north-west"])
        features["flooring"] = random.choice(["marble", "vitrified", "wooden", "granite", "ceramic"])
        features["corner_property"] = random.choice([True, False])
        features["gated_community"] = random.choice([True, False])
        features["pet_friendly"] = random.choice([True, False])
        
        # Location-specific features
        if location.name == "San Francisco":
            features["earthquake_resistant"] = random.choice([True, False])
            features["view_type"] = random.choice(["city", "bay", "park", "street"])
        elif location.name in ["Mumbai", "Gurgaon"]:
            features["vastu_compliant"] = random.choice([True, False])
            features["rainwater_harvesting"] = random.choice([True, False])
        
        return features
    
    def generate_realistic_amenities(self, property_type: PropertyType, location: LocationData, 
                                   num_amenities: Optional[int] = None) -> List[str]:
        """Generate realistic amenities based on property type and location"""
        if num_amenities is None:
            num_amenities = random.randint(5, 12)
        
        # Base amenities for all properties
        base_amenities = ["Security", "Power Backup", "Water Supply"]
        
        # Type-specific amenities
        if property_type in [PropertyType.APARTMENT, PropertyType.BUILDER_FLOOR]:
            base_amenities.extend(["Lift", "CCTV", "Intercom"])
        
        # Add location-specific popular amenities
        available_amenities = list(set(location.popular_amenities) - set(base_amenities))
        additional_count = max(0, min(num_amenities - len(base_amenities), len(available_amenities)))
        additional_amenities = random.sample(available_amenities, additional_count) if additional_count > 0 else []
        
        return base_amenities + additional_amenities
    
    def generate_user_preferences(self, location_key: str) -> Dict[str, Any]:
        """Generate realistic user preferences based on location"""
        location = self.locations[location_key]
        
        property_types = random.sample(list(PropertyType), random.randint(1, 2))
        purpose = random.choice(list(PropertyPurpose))
        
        # Location-specific budget ranges
        if location.currency == "USD":
            budget_min = random.randint(500000, 2000000)  # $500K - $2M
            budget_max = budget_min + random.randint(500000, 1500000)
        else:  # INR
            budget_min = random.randint(2000000, 10000000)  # 20L - 1Cr
            budget_max = budget_min + random.randint(2000000, 15000000)
        
        return {
            "property_type": [pt.value for pt in property_types],
            "purpose": purpose.value,
            "budget_min": budget_min,
            "budget_max": budget_max,
            "bedrooms_min": random.randint(1, 3),
            "bedrooms_max": random.randint(3, 6),
            "preferred_localities": random.sample(location.localities, random.randint(2, min(5, len(location.localities))))
        }
    
    def generate_booking_reference(self) -> str:
        """Generate unique booking reference"""
        return f"BK{datetime.now().strftime('%Y%m%d')}{random.randint(10000, 99999)}"
    
    def generate_future_date(self, min_days: int = 1, max_days: int = 60) -> datetime:
        """Generate a future date within specified range"""
        days_ahead = random.randint(min_days, max_days)
        return datetime.now() + timedelta(days=days_ahead)
    
    def generate_past_date(self, max_days_ago: int = 30) -> datetime:
        """Generate a past date within specified range"""
        days_ago = random.randint(1, max_days_ago)
        return datetime.now() - timedelta(days=days_ago)
    
    def weighted_choice(self, choices: List[Any], weights: List[float]) -> Any:
        """Make a weighted random choice"""
        return random.choices(choices, weights=weights)[0]
    
    def commit_with_rollback(self) -> bool:
        """Commit changes with rollback on error"""
        try:
            self.db.commit()
            return True
        except Exception as e:
            print(f"Error committing to database: {e}")
            self.db.rollback()
            return False
    
    def clear_table_data(self, model_class):
        """Clear all data from a specific table"""
        try:
            deleted_count = self.db.query(model_class).delete()
            self.db.commit()
            print(f"✅ Cleared {deleted_count} records from {model_class.__tablename__}")
        except Exception as e:
            print(f"⚠️  Error clearing {model_class.__tablename__}: {e}")
            self.db.rollback()

def create_database_session() -> Session:
    """Create and return a database session"""
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()

def get_default_config() -> DataConfig:
    """Get default data configuration"""
    return DataConfig()