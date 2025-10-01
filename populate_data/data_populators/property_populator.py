"""
Property data populator for testing with realistic location-based data
"""
import random
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import sys
import os
from sqlalchemy import select, delete

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.logging import get_logger
from app.models.properties import Property, PropertyImage, Amenity, PropertyAmenity
from app.models.users import User
from app.models.enums import PropertyType, PropertyPurpose, PropertyStatus
from .base import BasePopulator, LOCATIONS, VIRTUAL_TOUR_URL, MAIN_IMAGE_URL, OTHER_IMAGE_URL

logger = get_logger(__name__)

class PropertyPopulator(BasePopulator):
    """Populates test properties with realistic location-based data"""

    def __init__(self):
        super().__init__()

    @property
    def model_class(self):
        return Property

    @property
    def unique_fields(self) -> List[str]:
        return []  # Properties don't have uniqueness constraints - always create new ones
    
    def _generate_property_data(self, location_key: str, index: int, owner_id: int) -> Dict[str, Any]:
        """Generate realistic property data for a specific location"""
        location = LOCATIONS[location_key]
        
        # Property types and their characteristics
        property_types = [PropertyType.apartment, PropertyType.house, PropertyType.builder_floor, PropertyType.room]
        purposes = [PropertyPurpose.buy, PropertyPurpose.rent, PropertyPurpose.short_stay]
        
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
        if property_type == PropertyType.room:
            area_sqft = random.randint(200, 400)
            bedrooms = 1
            bathrooms = 1
        elif property_type == PropertyType.apartment:
            area_sqft = random.randint(600, 2500)
            bedrooms = random.randint(1, 4)
            bathrooms = min(bedrooms, random.randint(1, 3))
        elif property_type == PropertyType.builder_floor:
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
        if property_type == PropertyType.house:
            base_price = int(base_price * 1.2)
        elif property_type == PropertyType.room:
            base_price = int(base_price * 0.7)
        
        # Calculate other prices
        monthly_rent = int(base_price * 0.001) if purpose in [PropertyPurpose.rent, PropertyPurpose.short_stay] else None
        daily_rate = int(monthly_rent / 30) if purpose == PropertyPurpose.short_stay and monthly_rent else None
        security_deposit = int(monthly_rent * 2) if monthly_rent else None
        
        # We'll add amenities separately after property creation
        
        # Create property title
        property_type_str = property_type.value.replace('_', ' ').title()
        purpose_str = purpose.value.replace('_', ' ').title()
        
        titles = [
            f"Beautiful {bedrooms}BHK {property_type_str}",
            f"Spacious {bedrooms}BHK in {locality}",
            f"Premium {property_type_str} for {purpose_str}",
            f"Luxury {bedrooms}BHK with Modern Amenities",
            f"Well-maintained {property_type_str} in Prime Location"
        ]
        title = random.choice(titles)
        
        # Generate description
        description = f"""
{title} located in the heart of {locality}, {location.name}. 

This well-designed {property_type.value.replace('_', ' ')} offers {area_sqft} sq ft of living space with {bedrooms} bedrooms and {bathrooms} bathrooms. Perfect for {purpose.value.replace('_', ' ')}.

Key Features:
- Prime location in {locality}
- {area_sqft} sq ft carpet area
- {bedrooms} spacious bedrooms
- {bathrooms} modern bathrooms
- {'Parking available' if random.choice([True, False]) else 'Street parking'}

Modern amenities available for a comfortable living experience.

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
        if purpose == PropertyPurpose.short_stay:
            features.extend(["WiFi", "AC", "Kitchen"])
        
        # Create WKT location string for PostGIS
        location_wkt = f'SRID=4326;POINT({longitude} {latitude})'
        
        return {
            "owner_id": owner_id,
            "title": title,
            "description": description,
            "property_type": property_type,
            "purpose": purpose,
            "status": PropertyStatus.available,
            
            # Location
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "location": location_wkt,
            "city": location.name,
            "state": "Delhi" if location_key == "us" else ("Maharashtra" if location_key == "mumbai" else ("Haryana" if location_key == "gurgaon" else "Uttar Pradesh")),
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
            "max_occupancy": bedrooms * 2 if purpose == PropertyPurpose.short_stay else None,
            "minimum_stay_days": random.randint(1, 30) if purpose == PropertyPurpose.short_stay else 1,
            
            # Features
            "features": features,
            
            # Media
            "main_image_url": MAIN_IMAGE_URL,
            "virtual_tour_url": VIRTUAL_TOUR_URL,
            
            # Availability
            "is_available": True,
            "available_from": datetime.now(timezone.utc),
            
            # SEO and tags
            "tags": [property_type.value, purpose.value, locality, f"{bedrooms}bhk"],
            "search_keywords": f"{property_type.value} {purpose.value} {locality} {bedrooms}bhk {location.name}",
            
            # Owner/Builder info
            "owner_name": f"Owner {index + 1}",
            "owner_contact": f"+91{random.randint(6000000000, 9999999999)}" if location_key != "us" else f"+1{random.randint(2000000000, 9999999999)}",
            "builder_name": random.choice(location.builder_names),
            
            # Performance metrics
            "view_count": random.randint(10, 500),
            "like_count": random.randint(0, 50),
            "interest_count": random.randint(0, 20)
        }
    
    async def _create_property_images(self, session, property_id: int) -> None:
        """Create sample images for a property"""
        try:
            images = [
                PropertyImage(
                    property_id=property_id,
                    image_url=MAIN_IMAGE_URL,
                    caption="Main exterior view",
                    display_order=0,
                    is_main_image=True
                ),
                PropertyImage(
                    property_id=property_id,
                    image_url=OTHER_IMAGE_URL,
                    caption="Interior view",
                    display_order=1,
                    is_main_image=False
                ),
                PropertyImage(
                    property_id=property_id,
                    image_url=VIRTUAL_TOUR_URL,
                    caption="360° Virtual Tour",
                    display_order=2,
                    is_main_image=False
                )
            ]
            
            session.add_all(images)
            
        except Exception as e:
            self.logger.error(f"Failed to create images for property {property_id}: {str(e)}")
    
    async def _create_property_amenities(self, session, property_id: int, available_amenities: List[Amenity]) -> None:
        """Create amenity associations for a property"""
        try:
            if not available_amenities:
                return
            
            # Select 3-8 random amenities for this property
            num_amenities = random.randint(3, min(8, len(available_amenities)))
            selected_amenities = random.sample(available_amenities, num_amenities)
            
            for amenity in selected_amenities:
                property_amenity = PropertyAmenity(
                    property_id=property_id,
                    amenity_id=amenity.id
                )
                session.add(property_amenity)
            
        except Exception as e:
            self.logger.error(f"Failed to create amenities for property {property_id}: {str(e)}")
    
    async def populate_generated(
        self,
        count: Optional[int] = None,
        properties_per_location: Optional[int] = 100
    ) -> Dict[str, int]:
        """
        Create test properties across different locations with duplicate checking

        Args:
            count: Total number of properties to create (deprecated, use properties_per_location)
            properties_per_location: Number of properties to create per location (default: 100)

        Returns:
            Dict with 'created' and 'skipped' counts
        """
        # Handle backward compatibility
        if count is not None:
            # Calculate properties per location from total count
            location_keys = list(LOCATIONS.keys())
            properties_per_location = count // len(location_keys)
        elif properties_per_location is None:
            properties_per_location = 100

        location_keys = list(LOCATIONS.keys())
        total_properties = properties_per_location * len(location_keys)

        self.logger.info(f"Creating {properties_per_location} properties per location across {len(location_keys)} locations (total: {total_properties})...")

        # Generate all property data first
        property_data_list = []

        async with await self.get_db_session() as session:
            try:
                # Get available users to assign as property owners
                users_result = await session.execute(select(User))
                users = users_result.scalars().all()

                if not users:
                    self.logger.error("No users found to assign as property owners. Please create users first.")
                    return {"created": 0, "skipped": 0}

                # Get available amenities
                amenities_result = await session.execute(select(Amenity).where(Amenity.is_active == True))
                available_amenities = amenities_result.scalars().all()

                self.logger.info(f"Found {len(users)} users and {len(available_amenities)} amenities")

                for location_idx, location_key in enumerate(location_keys):
                    self.logger.info(f"Generating {properties_per_location} properties in {LOCATIONS[location_key].name}...")

                    for i in range(properties_per_location):
                        try:
                            # Since properties don't have uniqueness constraints, we generate them all
                            # Assign owner in round-robin fashion
                            owner = users[i % len(users)]
                            property_data = self._generate_property_data(location_key, i, owner.id)
                            property_data_list.append(property_data)

                        except Exception as e:
                            self.logger.error(f"Failed to generate property data {i + 1}: {str(e)}")
                            continue

                # Use base class populate method for creation (no duplicate checking for properties)
                result = await self.populate(property_data_list, skip_existing=False)

                # Now create images and amenities for the created properties
                if result["created"] > 0:
                    await self._create_images_and_amenities_for_created_properties(session, available_amenities)

                self.logger.info(f"Successfully created {result['created']} properties")

            except Exception as e:
                await session.rollback()
                self.logger.error(f"Failed to create properties: {str(e)}")
                raise

        return result

    async def _create_images_and_amenities_for_created_properties(self, session, available_amenities):
        """Create images and amenities for newly created properties"""
        try:
            # Get all properties that were just created (no images yet)
            # This is a bit hacky but works for our use case
            from sqlalchemy import outerjoin
            properties_result = await session.execute(
                select(Property)
                .outerjoin(PropertyImage, Property.id == PropertyImage.property_id)
                .where(PropertyImage.id.is_(None))
                .limit(1000)  # Limit to avoid memory issues
            )
            properties_without_images = properties_result.scalars().all()

            batch_size = 10
            for i in range(0, len(properties_without_images), batch_size):
                batch = properties_without_images[i:i + batch_size]

                for property_obj in batch:
                    try:
                        # Create property images
                        await self._create_property_images(session, property_obj.id)

                        # Create property amenities
                        await self._create_property_amenities(session, property_obj.id, available_amenities)

                    except Exception as e:
                        self.logger.error(f"Failed to create images/amenities for property {property_obj.id}: {str(e)}")
                        continue

                # Commit each batch
                await session.commit()
                self.logger.debug(f"Processed batch {i//batch_size + 1} of property images/amenities")

        except Exception as e:
            self.logger.error(f"Failed to create images and amenities: {str(e)}")
            raise
    
    async def clear_all(self) -> int:
        """Clear all test properties"""
        try:
            async with await self.get_db_session() as session:
                # Delete all properties - images will be cascade deleted
                result = await session.execute(delete(Property))
                deleted_count = result.rowcount
                
                await session.commit()
                
                self.logger.info(f"Deleted {deleted_count} properties")
                return deleted_count
            
        except Exception as e:
            self.logger.error(f"Failed to clear properties: {str(e)}")
            return 0