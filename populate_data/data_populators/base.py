"""
Base classes and utilities for data population
"""
import asyncio
from abc import ABC, abstractmethod
from typing import List, Optional
from dataclasses import dataclass
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.logging import get_logger

logger = get_logger(__name__)

@dataclass
class LocationData:
    """Location-specific data and configurations"""
    name: str
    latitude: float
    longitude: float
    localities: List[str]
    price_per_sqft_range: tuple[int, int]  # (min, max) in local currency
    currency: str
    popular_amenities: List[str]
    builder_names: List[str]
    landmarks: List[str]

# User-provided constants
VIRTUAL_TOUR_URL = "https://kuula.co/share/collection/71284?logo=-1&card=1&info=0&fs=1&vr=1&thumbs=3&alpha=0.71"
MAIN_IMAGE_URL = "https://www.nobroker.in/blog/wp-content/uploads/2023/11/Victory-Valley.jpg"
OTHER_IMAGE_URL = "https://preview.redd.it/tallest-building-in-gurgaon-v0-z90z4alcfn0b1.jpg"

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

class BasePopulator(ABC):
    """Base class for all data populators"""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
    
    @abstractmethod
    async def populate(self, count: Optional[int] = None) -> int:
        """
        Populate data for this entity type
        
        Args:
            count: Number of records to create (if applicable)
            
        Returns:
            Number of records created
        """
        pass
    
    def log_progress(self, current: int, total: int, entity_name: str):
        """Log progress of data creation"""
        if current % max(1, total // 10) == 0 or current == total:
            percentage = (current / total) * 100
            self.logger.info(f"Created {current}/{total} {entity_name} ({percentage:.1f}%)")