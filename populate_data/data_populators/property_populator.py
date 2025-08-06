"""
Property and PropertyImage data population across multiple locations
"""

import random
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from app.models.property import Property, PropertyImage, PropertyType, PropertyPurpose, PropertyStatus
from .base import DataPopulatorBase, DataConfig, LOCATIONS, VIRTUAL_TOUR_URL, MAIN_IMAGE_URL, OTHER_IMAGE_URL


class PropertyPopulator(DataPopulatorBase):
    """Handles creation of properties and their images across multiple locations"""
    
    def __init__(self, db_session, config: DataConfig):
        super().__init__(db_session, config)
        self.created_properties = []
    
    def create_properties_all_locations(self, properties_per_location: Optional[int] = None) -> List[Property]:
        """Create properties across all locations"""
        if properties_per_location is None:
            properties_per_location = self.config.properties_per_location
        
        print(f"Creating {properties_per_location} properties per location...")
        
        all_properties = []
        
        for location_key, location_data in self.locations.items():
            print(f"  Creating properties in {location_data.name}...")
            properties = self._create_properties_for_location(location_key, properties_per_location)
            all_properties.extend(properties)
        
        self.created_properties = all_properties
        print(f"✅ Created {len(all_properties)} properties across all locations")
        return all_properties
    
    def _create_properties_for_location(self, location_key: str, count: int) -> List[Property]:
        """Create properties for a specific location"""
        location = self.locations[location_key]
        properties = []
        
        # Distribution of property types and purposes
        type_distribution = self._get_property_type_distribution(location_key)
        purpose_distribution = self._get_property_purpose_distribution()
        status_distribution = self._get_property_status_distribution()
        
        for i in range(count):
            # Select property characteristics based on distributions
            property_type = self._weighted_choice_enum(PropertyType, type_distribution)
            purpose = self._weighted_choice_enum(PropertyPurpose, purpose_distribution)
            status = self._weighted_choice_enum(PropertyStatus, status_distribution)
            
            # Generate property details
            property_details = self._generate_property_details(property_type, location_key)
            pricing = self.generate_realistic_price(
                property_details["area_sqft"], location, property_type, purpose
            )
            
            # Generate coordinates within location bounds
            lat, lng = self.generate_coordinates_near(
                location.latitude, location.longitude, radius_km=15
            )
            
            # Create the property
            property_obj = Property(
                title=self._generate_property_title(property_details, location),
                description=self._generate_property_description(property_details, location),
                property_type=property_type,
                purpose=purpose,
                status=status,
                
                # Location data
                latitude=lat,
                longitude=lng,
                city=location.name,
                state=self._get_state_for_location(location_key),
                country=self._get_country_for_location(location_key),
                pincode=self._generate_pincode(location_key),
                locality=random.choice(location.localities),
                sub_locality=self.fake.street_name(),
                landmark=random.choice(location.landmarks),
                full_address=self._generate_full_address(location, property_details),
                area_type="residential",
                
                # Pricing
                **pricing,
                maintenance_charges=self._generate_maintenance_charges(purpose, pricing["base_price"]),
                
                # Property details
                **property_details,
                
                # Amenities and features
                amenities=self.generate_realistic_amenities(property_type, location),
                features=self.generate_property_features(property_type, location),
                
                # Media
                main_image_url=MAIN_IMAGE_URL,
                virtual_tour_url=VIRTUAL_TOUR_URL,
                
                # Availability
                is_available=status == PropertyStatus.AVAILABLE,
                available_from=self._generate_available_from_date(status),
                calendar_data=self._generate_calendar_data(purpose) if purpose == PropertyPurpose.SHORT_STAY else None,
                
                # SEO and search
                tags=self._generate_property_tags(property_details, location, property_type, purpose),
                search_keywords=self._generate_search_keywords(property_details, location),
                
                # Owner/Builder information
                owner_name=self.fake.name(),
                owner_contact=self._generate_phone_for_location(location_key),
                builder_name=random.choice(location.builder_names) if property_type == PropertyType.APARTMENT else None,
                
                # Performance metrics
                view_count=random.randint(10, 2000),
                like_count=random.randint(0, 150),
                interest_count=random.randint(0, 50)
            )
            
            self.db.add(property_obj)
            properties.append(property_obj)
            
            # Commit in batches for better performance
            if (i + 1) % 50 == 0:
                if self.commit_with_rollback():
                    print(f"    ✅ Created batch of properties in {location.name} (total: {i + 1})")
                else:
                    print(f"    ⚠️  Failed to create batch ending at property {i + 1}")
        
        # Final commit for remaining properties
        if self.commit_with_rollback():
            # Refresh all properties to get IDs
            for prop in properties:
                self.db.refresh(prop)
            
            # Create property images
            self._create_property_images(properties)
            
            print(f"  ✅ Created {len(properties)} properties in {location.name}")
            return properties
        else:
            raise Exception(f"Failed to create properties for {location.name}")
    
    def _create_property_images(self, properties: List[Property]):
        """Create multiple images for each property"""
        print(f"    Adding images for {len(properties)} properties...")
        
        image_categories = [
            "exterior", "living-room", "bedroom", "kitchen", "bathroom", 
            "balcony", "dining-room", "study", "common-area", "parking"
        ]
        
        for property_obj in properties:
            num_images = random.randint(4, 10)
            
            for j in range(num_images):
                # Use provided URLs for first few images, then generate others
                if j == 0:
                    image_url = OTHER_IMAGE_URL
                    caption = "Main View"
                    is_main = True
                elif j == 1:
                    image_url = MAIN_IMAGE_URL
                    caption = "Property Exterior"
                    is_main = False
                else:
                    category = random.choice(image_categories)
                    image_url = f"https://source.unsplash.com/800x600/?{category},apartment,house,interior"
                    caption = category.replace("-", " ").title()
                    is_main = False
                
                image = PropertyImage(
                    property_id=property_obj.id,
                    image_url=image_url,
                    caption=caption,
                    display_order=j,
                    is_main_image=is_main
                )
                self.db.add(image)
        
        if self.commit_with_rollback():
            print(f"    ✅ Added images for properties")
        else:
            print(f"    ⚠️  Failed to add images for properties")
    
    def _generate_property_details(self, property_type: PropertyType, location_key: str) -> Dict[str, Any]:
        """Generate property-specific details based on type"""
        details = {}
        
        if property_type == PropertyType.ROOM:
            details.update({
                "bedrooms": 1,
                "bathrooms": 1,
                "area_sqft": random.randint(150, 400),
                "balconies": 0,
                "parking_spaces": 0,
                "floor_number": random.randint(1, 5),
                "total_floors": random.randint(3, 10)
            })
        elif property_type == PropertyType.APARTMENT:
            bedrooms = random.choices([1, 2, 3, 4], weights=[0.2, 0.4, 0.3, 0.1])[0]
            details.update({
                "bedrooms": bedrooms,
                "bathrooms": random.randint(1, min(3, bedrooms + 1)),
                "area_sqft": random.randint(500 + bedrooms * 300, 1000 + bedrooms * 400),
                "balconies": random.randint(0, 2),
                "parking_spaces": random.randint(0, 2),
                "floor_number": random.randint(1, 30),
                "total_floors": random.randint(10, 35)
            })
        elif property_type == PropertyType.BUILDER_FLOOR:
            bedrooms = random.choices([2, 3, 4], weights=[0.3, 0.5, 0.2])[0]
            details.update({
                "bedrooms": bedrooms,
                "bathrooms": random.randint(2, bedrooms + 1),
                "area_sqft": random.randint(1000 + bedrooms * 200, 1500 + bedrooms * 300),
                "balconies": random.randint(1, 3),
                "parking_spaces": random.randint(1, 2),
                "floor_number": random.randint(0, 4),
                "total_floors": random.randint(3, 5)
            })
        else:  # HOUSE
            bedrooms = random.choices([3, 4, 5, 6], weights=[0.3, 0.4, 0.2, 0.1])[0]
            details.update({
                "bedrooms": bedrooms,
                "bathrooms": random.randint(2, bedrooms + 1),
                "area_sqft": random.randint(1500 + bedrooms * 250, 2500 + bedrooms * 500),
                "balconies": random.randint(1, 4),
                "parking_spaces": random.randint(1, 3),
                "floor_number": 0,  # Ground floor for houses
                "total_floors": random.randint(1, 3)
            })
        
        # Add common details
        details.update({
            "age_of_property": random.randint(0, 20),
            "max_occupancy": details["bedrooms"] * 2 if random.random() > 0.7 else None,
            "minimum_stay_days": random.choice([1, 2, 3, 7]) if random.random() > 0.8 else 1
        })
        
        return details
    
    def _generate_property_title(self, details: Dict, location) -> str:
        """Generate attractive property title"""
        templates = [
            f"{details['bedrooms']}BHK in Prime {random.choice(location.localities)}",
            f"Spacious {details['bedrooms']} Bedroom Home in {location.name}",
            f"Modern {details['bedrooms']}BHK with Great Amenities",
            f"Beautiful {details['bedrooms']} Bed Property in {random.choice(location.localities)}"
        ]
        return random.choice(templates)
    
    def _generate_property_description(self, details: Dict, location) -> str:
        """Generate detailed property description"""
        size_desc = f"{details['area_sqft']} sq.ft"
        location_desc = f"prime location of {random.choice(location.localities)}, {location.name}"
        
        features = []
        if details.get("parking_spaces", 0) > 0:
            features.append(f"{details['parking_spaces']} parking space(s)")
        if details.get("balconies", 0) > 0:
            features.append(f"{details['balconies']} balcony/balconies")
        
        feature_text = ", ".join(features) if features else "excellent amenities"
        
        description = (f"Beautiful {details['bedrooms']}BHK property located in {location_desc}. "
                      f"This property offers {size_desc} of living space with {feature_text} "
                      f"and modern conveniences. Perfect for comfortable living with easy access "
                      f"to all major facilities and transport links.")
        
        return description
    
    def _get_property_type_distribution(self, location_key: str) -> Dict[PropertyType, float]:
        """Get property type distribution based on location"""
        if location_key == "us":
            return {
                PropertyType.APARTMENT: 0.6,
                PropertyType.HOUSE: 0.25,
                PropertyType.ROOM: 0.1,
                PropertyType.BUILDER_FLOOR: 0.05
            }
        else:  # Mumbai, Gurgaon
            return {
                PropertyType.APARTMENT: 0.5,
                PropertyType.BUILDER_FLOOR: 0.25,
                PropertyType.HOUSE: 0.15,
                PropertyType.ROOM: 0.1
            }
    
    def _get_property_purpose_distribution(self) -> Dict[PropertyPurpose, float]:
        """Get property purpose distribution"""
        return {
            PropertyPurpose.BUY: 0.4,
            PropertyPurpose.RENT: 0.45,
            PropertyPurpose.SHORT_STAY: 0.15
        }
    
    def _get_property_status_distribution(self) -> Dict[PropertyStatus, float]:
        """Get property status distribution"""
        return {
            PropertyStatus.AVAILABLE: 0.7,
            PropertyStatus.SOLD: 0.1,
            PropertyStatus.RENTED: 0.12,
            PropertyStatus.UNDER_OFFER: 0.05,
            PropertyStatus.MAINTENANCE: 0.03
        }
    
    def _weighted_choice_enum(self, enum_class, distribution: Dict) -> Any:
        """Make weighted choice from enum based on distribution"""
        choices = list(distribution.keys())
        weights = list(distribution.values())
        return random.choices(choices, weights=weights)[0]
    
    def _get_state_for_location(self, location_key: str) -> str:
        """Get state/province for location"""
        states = {
            "us": "California",
            "mumbai": "Maharashtra", 
            "gurgaon": "Haryana"
        }
        return states.get(location_key, "Unknown")
    
    def _get_country_for_location(self, location_key: str) -> str:
        """Get country for location"""
        return "USA" if location_key == "us" else "India"
    
    def _generate_pincode(self, location_key: str) -> str:
        """Generate realistic pincode for location"""
        if location_key == "us":
            return f"94{random.randint(100, 199)}"  # SF area codes
        elif location_key == "mumbai":
            return f"40{random.randint(10, 99):02d}"  # Mumbai codes
        else:  # gurgaon
            return f"1220{random.randint(10, 99)}"  # Gurgaon codes
    
    def _generate_phone_for_location(self, location_key: str) -> str:
        """Generate phone number for location"""
        if location_key == "us":
            return f"+1{self.fake_us.numerify('##########')}"
        else:
            return f"+91{self.fake_in.numerify('##########')}"
    
    def _generate_full_address(self, location, details: Dict) -> str:
        """Generate full address"""
        street = self.fake.street_address()
        locality = random.choice(location.localities)
        return f"{street}, {locality}, {location.name}"
    
    def _generate_maintenance_charges(self, purpose: PropertyPurpose, base_price: float) -> Optional[float]:
        """Generate maintenance charges if applicable"""
        if purpose == PropertyPurpose.BUY:
            return None
        return random.randint(2000, 8000) if purpose == PropertyPurpose.RENT else random.randint(500, 2000)
    
    def _generate_available_from_date(self, status: PropertyStatus) -> str:
        """Generate available from date based on status"""
        if status == PropertyStatus.AVAILABLE:
            # Available immediately or within 30 days
            days_ahead = random.randint(0, 30)
            date = datetime.now() + timedelta(days=days_ahead)
        else:
            # Future date for non-available properties
            days_ahead = random.randint(30, 365)
            date = datetime.now() + timedelta(days=days_ahead)
        
        return date.strftime("%Y-%m-%d")
    
    def _generate_calendar_data(self, purpose: PropertyPurpose) -> Optional[Dict]:
        """Generate calendar data for short stay properties"""
        if purpose != PropertyPurpose.SHORT_STAY:
            return None
        
        # Generate availability calendar for next 90 days
        calendar = {}
        for i in range(90):
            date = (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d")
            calendar[date] = {
                "available": random.random() > 0.3,  # 70% availability
                "price_override": None if random.random() > 0.2 else random.randint(50, 200)
            }
        
        return calendar
    
    def _generate_property_tags(self, details: Dict, location, property_type: PropertyType, purpose: PropertyPurpose) -> List[str]:
        """Generate SEO tags for property"""
        tags = [
            property_type.value,
            purpose.value,
            f"{details['bedrooms']}bhk",
            location.name.lower(),
            random.choice(location.localities).lower().replace(" ", "-")
        ]
        
        # Add additional tags based on features
        if details.get("parking_spaces", 0) > 0:
            tags.append("parking")
        if details.get("balconies", 0) > 0:
            tags.append("balcony")
        if details["area_sqft"] > 1500:
            tags.append("spacious")
        
        return list(set(tags))  # Remove duplicates
    
    def _generate_search_keywords(self, details: Dict, location) -> str:
        """Generate search keywords"""
        keywords = [
            f"{details['bedrooms']}bhk",
            "property",
            location.name.lower(),
            random.choice(location.localities).lower(),
            "rent" if random.random() > 0.5 else "buy"
        ]
        return " ".join(keywords)
    
    def get_created_properties(self) -> List[Property]:
        """Get all created properties"""
        return self.created_properties
    
    def clear_existing_data(self):
        """Clear existing property data"""
        print("Clearing existing property and property image data...")
        self.clear_table_data(PropertyImage)
        self.clear_table_data(Property)