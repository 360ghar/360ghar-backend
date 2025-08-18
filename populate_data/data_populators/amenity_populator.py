"""
Amenity data populator for creating predefined amenities
"""
from typing import Optional
import sys
import os
from sqlalchemy import select, delete

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.logging import get_logger
from app.models.models import Amenity
from .base import BasePopulator

logger = get_logger(__name__)

class AmenityPopulator(BasePopulator):
    """Populates predefined amenities in the database"""
    
    def __init__(self):
        super().__init__()
    
    async def populate(self, count: Optional[int] = None) -> int:
        """
        Create predefined amenities
        
        Args:
            count: Not used for amenities (creates predefined set)
            
        Returns:
            Number of amenities created
        """
        self.logger.info("Creating predefined amenities...")
        
        # Predefined amenities with icons (using common icon names)
        amenities_data = [
            # Safety & Security
            {"title": "Security", "icon": "shield-check", "category": "safety"},
            {"title": "CCTV", "icon": "camera", "category": "safety"},
            {"title": "Gated Community", "icon": "gate", "category": "safety"},
            {"title": "24/7 Security", "icon": "clock", "category": "safety"},
            {"title": "Intercom", "icon": "phone", "category": "safety"},
            {"title": "Fire Safety", "icon": "fire", "category": "safety"},
            
            # Recreation & Entertainment
            {"title": "Swimming Pool", "icon": "pool", "category": "recreation"},
            {"title": "Gym", "icon": "dumbbell", "category": "recreation"},
            {"title": "Fitness Center", "icon": "fitness", "category": "recreation"},
            {"title": "Clubhouse", "icon": "building", "category": "recreation"},
            {"title": "Children's Play Area", "icon": "playground", "category": "recreation"},
            {"title": "Sports Court", "icon": "tennis-ball", "category": "recreation"},
            {"title": "Jogging Track", "icon": "running", "category": "recreation"},
            {"title": "Garden", "icon": "tree", "category": "recreation"},
            {"title": "Park", "icon": "park", "category": "recreation"},
            
            # Convenience & Utilities
            {"title": "Parking", "icon": "car", "category": "convenience"},
            {"title": "Covered Parking", "icon": "garage", "category": "convenience"},
            {"title": "Lift", "icon": "elevator", "category": "convenience"},
            {"title": "Elevator", "icon": "elevator", "category": "convenience"},
            {"title": "Power Backup", "icon": "battery", "category": "utilities"},
            {"title": "Generator", "icon": "generator", "category": "utilities"},
            {"title": "Water Supply", "icon": "water", "category": "utilities"},
            {"title": "Borewell", "icon": "drill", "category": "utilities"},
            {"title": "Rainwater Harvesting", "icon": "droplets", "category": "utilities"},
            {"title": "Waste Management", "icon": "trash", "category": "utilities"},
            {"title": "Maintenance", "icon": "tools", "category": "services"},
            
            # Modern Amenities
            {"title": "WiFi", "icon": "wifi", "category": "convenience"},
            {"title": "Internet", "icon": "internet", "category": "convenience"},
            {"title": "Cable TV", "icon": "tv", "category": "convenience"},
            {"title": "Air Conditioning", "icon": "ac", "category": "convenience"},
            {"title": "Central AC", "icon": "ac-central", "category": "convenience"},
            {"title": "Heating", "icon": "thermometer", "category": "convenience"},
            
            # Services
            {"title": "Concierge", "icon": "user-tie", "category": "services"},
            {"title": "Housekeeping", "icon": "broom", "category": "services"},
            {"title": "Laundry", "icon": "washing-machine", "category": "services"},
            {"title": "Grocery Store", "icon": "shopping-cart", "category": "services"},
            {"title": "Medical Center", "icon": "medical", "category": "services"},
            
            # Accessibility
            {"title": "Wheelchair Accessible", "icon": "wheelchair", "category": "accessibility"},
            {"title": "Senior Friendly", "icon": "elderly", "category": "accessibility"},
            {"title": "Pet Friendly", "icon": "pet", "category": "accessibility"},
            
            # Location Benefits
            {"title": "Metro Connectivity", "icon": "train", "category": "convenience"},
            {"title": "Bus Stop Nearby", "icon": "bus", "category": "convenience"},
            {"title": "Airport Nearby", "icon": "plane", "category": "convenience"},
            {"title": "Mall Nearby", "icon": "shopping-bag", "category": "convenience"},
            {"title": "School Nearby", "icon": "school", "category": "convenience"},
            {"title": "Hospital Nearby", "icon": "hospital", "category": "convenience"},
        ]
        
        created_count = 0
        
        async with await self.get_db_session() as session:
            try:
                for amenity_data in amenities_data:
                    try:
                        # Check if amenity already exists
                        existing_amenity = await session.execute(
                            select(Amenity).where(Amenity.title == amenity_data["title"])
                        )
                        if existing_amenity.scalar_one_or_none():
                            self.logger.debug(f"Amenity '{amenity_data['title']}' already exists, skipping...")
                            continue
                        
                        # Create amenity
                        amenity = Amenity(**amenity_data)
                        session.add(amenity)
                        created_count += 1
                        
                        self.logger.debug(f"Created amenity: {amenity_data['title']}")
                        
                    except Exception as e:
                        self.logger.error(f"Failed to create amenity {amenity_data['title']}: {str(e)}")
                        continue
                
                await session.commit()
                self.logger.info(f"Successfully created {created_count} amenities")
                
            except Exception as e:
                await session.rollback()
                self.logger.error(f"Failed to create amenities: {str(e)}")
                raise
        
        return created_count
    
    async def clear_all(self) -> int:
        """Clear all amenities"""
        try:
            async with await self.get_db_session() as session:
                # Delete all amenities
                result = await session.execute(delete(Amenity))
                deleted_count = result.rowcount
                
                await session.commit()
                
                self.logger.info(f"Deleted {deleted_count} amenities")
                return deleted_count
            
        except Exception as e:
            self.logger.error(f"Failed to clear amenities: {str(e)}")
            return 0