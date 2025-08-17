"""
Property data populator for testing with realistic location-based data
"""
import random
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.supabase_client import get_supabase_admin_client
from app.core.logging import get_logger
from app.db.base import BaseRepository
from .base import BasePopulator, LOCATIONS, VIRTUAL_TOUR_URL, MAIN_IMAGE_URL, OTHER_IMAGE_URL

logger = get_logger(__name__)

class PropertyPopulator(BasePopulator):
    """Populates test properties with realistic location-based data"""
    
    def __init__(self):
        self.client = get_supabase_admin_client()
        self.property_repo = BaseRepository(self.client, "properties")
        self.property_images_repo = BaseRepository(self.client, "property_images")
        self.logger = get_logger(self.__class__.__name__)
    
    def _generate_property_data(self, location_key: str, index: int) -> Dict[str, Any]:
        """Generate realistic property data for a specific location"""
        location = LOCATIONS[location_key]
        
        # Property types and their characteristics
        property_types = ["apartment", "house", "builder_floor", "room"]
        purposes = ["buy", "rent", "short_stay"]
        
        property_type = random.choice(property_types)
        purpose = random.choice(purposes)
        
        # Generate location within city bounds
        # Add some random offset to create variety around the city center
        lat_offset = random.uniform(-0.1, 0.1)  # ~11km radius
        lng_offset = random.uniform(-0.1, 0.1)
        
        latitude = location.latitude + lat_offset
        longitude = location.longitude + lng_offset
        
        # Select random locality
        locality = random.choice(location.localities)
        
        # Generate area based on property type
        if property_type == "room":
            area_sqft = random.randint(200, 400)
            bedrooms = 1
            bathrooms = 1
        elif property_type == "apartment":
            area_sqft = random.randint(600, 2500)
            bedrooms = random.randint(1, 4)
            bathrooms = min(bedrooms, random.randint(1, 3))
        elif property_type == "builder_floor":
            area_sqft = random.randint(1200, 3000)
            bedrooms = random.randint(2, 4)
            bathrooms = random.randint(2, 4)
        else:  # house
            area_sqft = random.randint(1500, 5000)
            bedrooms = random.randint(2, 6)
            bathrooms = random.randint(2, 5)
        
        # Generate price based on location and area
        price_per_sqft = random.randint(*location.price_per_sqft_range)
        base_price = area_sqft * price_per_sqft
        
        # Adjust for property type
        if property_type == "house":
            base_price = int(base_price * 1.2)
        elif property_type == "room":
            base_price = int(base_price * 0.7)
        
        # Calculate other prices
        monthly_rent = int(base_price * 0.001) if purpose in ["rent", "short_stay"] else None
        daily_rate = int(monthly_rent / 30) if purpose == "short_stay" and monthly_rent else None
        security_deposit = int(monthly_rent * 2) if monthly_rent else None
        
        # Generate amenities
        selected_amenities = random.sample(
            location.popular_amenities, 
            random.randint(3, min(8, len(location.popular_amenities)))
        )
        
        # Create property title
        titles = [
            f"Beautiful {bedrooms}BHK {property_type.replace('_', ' ').title()}",
            f"Spacious {bedrooms}BHK in {locality}",
            f"Premium {property_type.replace('_', ' ').title()} for {purpose.replace('_', ' ').title()}",
            f"Luxury {bedrooms}BHK with Modern Amenities",
            f"Well-maintained {property_type.replace('_', ' ').title()} in Prime Location"
        ]
        title = random.choice(titles)
        
        # Generate description
        description = f"""
{title} located in the heart of {locality}, {location.name}. 

This well-designed {property_type.replace('_', ' ')} offers {area_sqft} sq ft of living space with {bedrooms} bedrooms and {bathrooms} bathrooms. Perfect for {purpose.replace('_', ' ')}.

Key Features:
- Prime location in {locality}
- {area_sqft} sq ft carpet area
- {bedrooms} spacious bedrooms
- {bathrooms} modern bathrooms
- {'Parking available' if random.choice([True, False]) else 'Street parking'}

Amenities: {', '.join(selected_amenities)}

{random.choice(location.landmarks)} - This property offers excellent connectivity and lifestyle amenities.
        """.strip()
        
        # Additional property features
        features = []
        if random.choice([True, False]):
            features.append("Fully Furnished")
        if random.choice([True, False]):
            features.append("Pet Friendly")
        if random.choice([True, False]):
            features.append("24/7 Security")
        if purpose == "short_stay":
            features.extend(["WiFi", "AC", "Kitchen"])
        
        return {
            "title": title,
            "description": description,
            "property_type": property_type,
            "purpose": purpose,
            "status": "available",
            
            # Location
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "city": location.name,
            "state": "Delhi" if location_key == "us" else ("Maharashtra" if location_key == "mumbai" else "Haryana"),
            "country": "USA" if location_key == "us" else "India",
            "pincode": f"{random.randint(100000, 999999)}",
            "locality": locality,
            "sub_locality": f"Sector {random.randint(1, 50)}" if "Sector" not in locality else None,
            "landmark": random.choice(location.landmarks),
            "full_address": f"{locality}, {location.name}",
            "area_type": "Built-up Area",
            
            # Pricing
            "base_price": base_price,
            "price_per_sqft": price_per_sqft,
            "monthly_rent": monthly_rent,
            "daily_rate": daily_rate,
            "security_deposit": security_deposit,
            "maintenance_charges": random.randint(1000, 5000) if location_key != "us" else random.randint(50, 200),
            
            # Property details
            "area_sqft": area_sqft,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "balconies": random.randint(0, 2),
            "parking_spaces": random.randint(0, 2),
            "floor_number": random.randint(1, 20),
            "total_floors": random.randint(5, 25),
            "age_of_property": random.randint(0, 20),
            
            # Short stay specific
            "max_occupancy": bedrooms * 2 if purpose == "short_stay" else None,
            "minimum_stay_days": random.randint(1, 30) if purpose == "short_stay" else 1,
            
            # Amenities and features
            "amenities": selected_amenities,
            "features": features,
            
            # Media
            "main_image_url": MAIN_IMAGE_URL,
            "virtual_tour_url": VIRTUAL_TOUR_URL,
            
            # Availability
            "is_available": True,
            "available_from": "Immediate",
            
            # SEO and tags
            "tags": [property_type, purpose, locality, f"{bedrooms}bhk"],
            "search_keywords": f"{property_type} {purpose} {locality} {bedrooms}bhk {location.name}",
            
            # Owner/Builder info
            "owner_name": f"Owner {index + 1}",
            "owner_contact": f"+91{random.randint(6000000000, 9999999999)}" if location_key != "us" else f"+1{random.randint(2000000000, 9999999999)}",
            "builder_name": random.choice(location.builder_names),
            
            # Performance metrics
            "view_count": random.randint(10, 500),
            "like_count": random.randint(0, 50),
            "interest_count": random.randint(0, 20)
        }
    
    async def _create_property_images(self, property_id: int) -> None:
        """Create sample images for a property"""
        try:
            images = [
                {
                    "property_id": property_id,
                    "image_url": MAIN_IMAGE_URL,
                    "caption": "Main exterior view",
                    "display_order": 0,
                    "is_main_image": True
                },
                {
                    "property_id": property_id,
                    "image_url": OTHER_IMAGE_URL,
                    "caption": "Interior view",
                    "display_order": 1,
                    "is_main_image": False
                },
                {
                    "property_id": property_id,
                    "image_url": VIRTUAL_TOUR_URL,
                    "caption": "360° Virtual Tour",
                    "display_order": 2,
                    "is_main_image": False
                }
            ]
            
            await self.property_images_repo.batch_insert(images)
            
        except Exception as e:
            self.logger.error(f"Failed to create images for property {property_id}: {str(e)}")
    
    async def populate(self, count: Optional[int] = 300) -> int:
        """
        Create test properties across different locations
        
        Args:
            count: Number of properties to create (default: 300)
            
        Returns:
            Number of properties created
        """
        if count is None:
            count = 1000
            
        self.logger.info(f"Creating {count} test properties across locations...")
        
        created_count = 0
        location_keys = list(LOCATIONS.keys())
        
        # Distribute properties across locations
        properties_per_location = count // len(location_keys)
        remainder = count % len(location_keys)
        
        for location_idx, location_key in enumerate(location_keys):
            # Add remainder to first few locations
            location_count = properties_per_location + (1 if location_idx < remainder else 0)
            
            self.logger.info(f"Creating {location_count} properties in {LOCATIONS[location_key].name}...")
            
            for i in range(location_count):
                try:
                    property_data = self._generate_property_data(location_key, created_count)
                    
                    # Create property
                    property_result = await self.property_repo.create(property_data)
                    
                    # Create property images
                    if property_result and "id" in property_result:
                        await self._create_property_images(property_result["id"])
                    
                    created_count += 1
                    self.log_progress(created_count, count, "properties")
                    
                except Exception as e:
                    self.logger.error(f"Failed to create property {created_count + 1}: {str(e)}")
                    continue
        
        self.logger.info(f"Successfully created {created_count} properties")
        return created_count
    
    async def clear_all(self) -> int:
        """Clear all test properties"""
        try:
            # Get count before deletion
            count_result = await self.property_repo.count()
            
            # Note: Since we're using cascade deletes, property_images will be automatically deleted
            # For this test data, we'll delete all properties
            # In production, you might want to be more selective
            
            # Get all property IDs first
            all_properties = await self.property_repo.get_multi(limit=10000)  # Get all
            
            deleted_count = 0
            for property_data in all_properties.get("items", []):
                try:
                    await self.property_repo.delete(property_data["id"])
                    deleted_count += 1
                except Exception as e:
                    self.logger.error(f"Failed to delete property {property_data['id']}: {str(e)}")
            
            self.logger.info(f"Deleted {deleted_count} properties")
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Failed to clear properties: {str(e)}")
            return 0