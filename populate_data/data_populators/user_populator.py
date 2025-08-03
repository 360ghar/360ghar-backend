"""
User and Relationship Manager data population
"""

import json
import random
from typing import List, Dict, Any, Optional
from faker import Faker

from app.models.user import User
from app.models.visit import RelationshipManager
from .base import DataPopulatorBase, DataConfig, LOCATIONS


class UserPopulator(DataPopulatorBase):
    """Handles creation of users and relationship managers"""
    
    def __init__(self, db_session, config: DataConfig):
        super().__init__(db_session, config)
        self.created_users = []
        self.created_rms = []
    
    def create_main_user(self) -> User:
        """Create the main user with specific Supabase ID as requested"""
        print("Creating main user (saksham1991999@gmail.com)...")
        
        main_user = User(
            supabase_user_id="3961aff5-00c8-4f34-9213-25649ecb55e3",
            email="saksham1991999@gmail.com",
            phone="+919876543210",
            full_name="Saksham Mittal",
            date_of_birth=self.fake.date_of_birth(minimum_age=25, maximum_age=35),
            profile_image_url=f"https://i.pravatar.cc/300?u=saksham",
            is_active=True,
            is_verified=True,
            current_latitude=str(LOCATIONS["gurgaon"].latitude),
            current_longitude=str(LOCATIONS["gurgaon"].longitude),
            preferences=self.generate_user_preferences("gurgaon"),
            preferred_locations=["Gurgaon", "Delhi", "Mumbai"],
            notification_settings={
                "email_notifications": True,
                "push_notifications": True,
                "sms_notifications": True
            },
            privacy_settings={
                "profile_visibility": "public",
                "location_sharing": True
            }
        )
        
        self.db.add(main_user)
        if self.commit_with_rollback():
            self.db.refresh(main_user)
            self.created_users.append(main_user)
            print(f"✅ Created main user: {main_user.email} (ID: {main_user.id})")
            return main_user
        else:
            raise Exception("Failed to create main user")
    
    def create_diverse_users(self, count: Optional[int] = None) -> List[User]:
        """Create diverse user profiles across all locations"""
        if count is None:
            count = self.config.users_count
        
        print(f"Creating {count} diverse users...")
        
        users = []
        location_keys = list(LOCATIONS.keys())
        
        for i in range(count):
            # Distribute users across locations
            location_key = location_keys[i % len(location_keys)]
            location = LOCATIONS[location_key]
            
            # Generate coordinates near the location
            lat, lng = self.generate_coordinates_near(
                location.latitude, 
                location.longitude, 
                radius_km=random.randint(5, 20)
            )
            
            # Choose appropriate faker based on location
            if location_key == "us":
                faker = self.fake_us
                phone_prefix = "+1"
            else:
                faker = self.fake_in
                phone_prefix = "+91"
            
            # Generate user activity level (affects interaction patterns later)
            activity_levels = ["low", "medium", "high"]
            activity_weights = [0.3, 0.5, 0.2]  # Most users have medium activity
            activity_level = self.weighted_choice(activity_levels, activity_weights)
            
            # Generate realistic verification status (higher for active users)
            is_verified = activity_level == "high" or random.random() > 0.3
            
            user = User(
                supabase_user_id=faker.uuid4(),
                email=faker.email(),
                phone=f"{phone_prefix}{faker.numerify('##########')}",
                full_name=faker.name(),
                date_of_birth=faker.date_of_birth(minimum_age=22, maximum_age=55),
                profile_image_url=f"https://i.pravatar.cc/300?img={i+10}",
                is_active=True,
                is_verified=is_verified,
                current_latitude=str(lat),
                current_longitude=str(lng),
                preferences=self.generate_user_preferences(location_key),
                preferred_locations=self._generate_preferred_locations(location_key),
                notification_settings=self._generate_notification_settings(activity_level),
                privacy_settings=self._generate_privacy_settings()
            )
            
            # Store activity level for use by other populators
            user._activity_level = activity_level
            user._location_key = location_key
            
            self.db.add(user)
            users.append(user)
            
            # Commit in batches for better performance
            if (i + 1) % 20 == 0:
                if self.commit_with_rollback():
                    print(f"  ✅ Created batch of users (total: {i + 1})")
                else:
                    print(f"  ⚠️  Failed to create batch ending at user {i + 1}")
        
        # Final commit for remaining users
        if self.commit_with_rollback():
            # Refresh all users to get IDs
            for user in users:
                self.db.refresh(user)
            
            self.created_users.extend(users)
            print(f"✅ Created {len(users)} diverse users across all locations")
            return users
        else:
            raise Exception("Failed to create users")
    
    def create_relationship_managers(self, count: Optional[int] = None) -> List[RelationshipManager]:
        """Create relationship managers for handling visits"""
        if count is None:
            count = self.config.relationship_managers_count
        
        print(f"Creating {count} relationship managers...")
        
        rms = []
        departments = ["Customer Relations", "Sales", "Property Management", "Client Services"]
        
        for i in range(count):
            # Generate working hours
            working_hours = {
                "monday": "9:00 AM - 6:00 PM",
                "tuesday": "9:00 AM - 6:00 PM", 
                "wednesday": "9:00 AM - 6:00 PM",
                "thursday": "9:00 AM - 6:00 PM",
                "friday": "9:00 AM - 6:00 PM",
                "saturday": "10:00 AM - 4:00 PM" if random.random() > 0.3 else "Closed",
                "sunday": "Closed" if random.random() > 0.1 else "10:00 AM - 2:00 PM"
            }
            
            # Generate experience and performance metrics
            experience_years = random.randint(1, 15)
            total_visits = random.randint(20, 500)
            rating = round(random.uniform(3.5, 5.0), 1)
            
            rm = RelationshipManager(
                name=self.fake_in.name(),
                email=self.fake_in.email(),
                phone=f"+91{self.fake_in.numerify('##########')}",
                whatsapp_number=f"+91{self.fake_in.numerify('##########')}",
                profile_image_url=f"https://i.pravatar.cc/200?img={i+50}",
                bio=self._generate_rm_bio(experience_years),
                employee_id=f"RM{2024000 + i:03d}",
                department=random.choice(departments),
                experience_years=experience_years,
                is_active=random.random() > 0.05,  # 95% active
                working_hours=json.dumps(working_hours),
                total_visits_handled=total_visits,
                customer_rating=str(rating)
            )
            
            self.db.add(rm)
            rms.append(rm)
        
        if self.commit_with_rollback():
            # Refresh all RMs to get IDs
            for rm in rms:
                self.db.refresh(rm)
            
            self.created_rms.extend(rms)
            print(f"✅ Created {len(rms)} relationship managers")
            return rms
        else:
            raise Exception("Failed to create relationship managers")
    
    def _generate_preferred_locations(self, primary_location_key: str) -> List[str]:
        """Generate preferred locations for a user based on their primary location"""
        primary_location = LOCATIONS[primary_location_key]
        locations = [primary_location.name]
        
        # Add 1-3 additional preferred locations
        other_locations = [loc.name for key, loc in LOCATIONS.items() if key != primary_location_key]
        additional_count = random.randint(1, min(3, len(other_locations)))
        locations.extend(random.sample(other_locations, additional_count))
        
        return locations
    
    def _generate_notification_settings(self, activity_level: str) -> Dict[str, bool]:
        """Generate notification preferences based on user activity level"""
        if activity_level == "high":
            return {
                "email_notifications": True,
                "push_notifications": True,
                "sms_notifications": random.choice([True, False])
            }
        elif activity_level == "medium":
            return {
                "email_notifications": random.choice([True, False]),
                "push_notifications": True,
                "sms_notifications": False
            }
        else:  # low activity
            return {
                "email_notifications": False,
                "push_notifications": random.choice([True, False]),
                "sms_notifications": False
            }
    
    def _generate_privacy_settings(self) -> Dict[str, Any]:
        """Generate privacy settings"""
        return {
            "profile_visibility": random.choice(["public", "private"]),
            "location_sharing": random.choice([True, False])
        }
    
    def _generate_rm_bio(self, experience_years: int) -> str:
        """Generate a realistic bio for relationship manager"""
        templates = [
            f"Experienced real estate professional with {experience_years} years in property sales and customer relations. Specialized in helping clients find their dream homes.",
            f"Dedicated relationship manager with {experience_years} years of experience in the real estate industry. Passionate about connecting people with perfect properties.",
            f"Real estate expert with {experience_years} years of hands-on experience. Committed to providing exceptional service and building lasting client relationships.",
            f"Property consultant with {experience_years} years in the industry. Expert in market analysis and helping clients make informed property decisions."
        ]
        return random.choice(templates)
    
    def get_created_users(self) -> List[User]:
        """Get all created users"""
        return self.created_users
    
    def get_created_relationship_managers(self) -> List[RelationshipManager]:
        """Get all created relationship managers"""
        return self.created_rms
    
    def clear_existing_data(self):
        """Clear existing user and RM data"""
        print("Clearing existing user and relationship manager data...")
        self.clear_table_data(User)
        self.clear_table_data(RelationshipManager)