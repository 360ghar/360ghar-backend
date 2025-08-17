"""
User data populator for testing
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.supabase_client import get_supabase_admin_client
from app.core.logging import get_logger
from app.db.base import BaseRepository
from .base import BasePopulator

logger = get_logger(__name__)

class UserPopulator(BasePopulator):
    """Populates test users in the database"""
    
    def __init__(self):
        self.client = get_supabase_admin_client()
        self.user_repo = BaseRepository(self.client, "users")
        self.logger = get_logger(self.__class__.__name__)
    
    async def populate(self, count: Optional[int] = 2) -> int:
        """
        Create test users
        
        Note: User creation requires valid Supabase auth users due to foreign key constraints.
        For testing purposes, this populator will log the limitation and skip user creation.
        To test with real users, create them via Supabase Auth first.
        
        Args:
            count: Number of users to create (default: 2)
            
        Returns:
            Number of users created
        """
        if count is None:
            count = 2
            
        self.logger.info(f"Attempting to create {count} test users...")
        self.logger.warning("User creation skipped: Requires real Supabase Auth users due to FK constraints")
        self.logger.info("To test with users: Create them via Supabase Auth, then sync via API endpoints")
        
        return 0  # Skip creation for now
        
        # Note: Below is the test user data that would be used if FK constraints were bypassed
        # Test user data
        test_users = [
            {
                "email": "testuser1@360ghar.com",
                "full_name": "Raj Sharma",
                "phone": "+919876543210",
                "date_of_birth": "1990-05-15",
                "is_active": True,
                "is_verified": True,
                "current_latitude": 28.4595,  # Gurgaon
                "current_longitude": 77.0266,
                "preferences": {
                    "property_type": ["apartment", "builder_floor"],
                    "purpose": "rent",
                    "budget_min": 25000,
                    "budget_max": 50000,
                    "bedrooms_min": 2,
                    "bedrooms_max": 3,
                    "area_min": 1000,
                    "area_max": 1500,
                    "location_preference": ["DLF Phase 1", "DLF Phase 2", "Sector 29"],
                    "max_distance_km": 10
                },
                "preferred_locations": ["Gurgaon", "DLF Phase 1", "Cyber City"],
                "notification_settings": {
                    "email_notifications": True,
                    "push_notifications": True,
                    "sms_notifications": False
                },
                "privacy_settings": {
                    "profile_visibility": "public",
                    "location_sharing": True
                },
                "profile_image_url": "https://api.dicebear.com/7.x/avataaars/svg?seed=Raj"
            },
            {
                "email": "testuser2@360ghar.com",
                "full_name": "Priya Patel",
                "phone": "+919876543211",
                "date_of_birth": "1988-08-22",
                "is_active": True,
                "is_verified": True,
                "current_latitude": 19.0760,  # Mumbai
                "current_longitude": 72.8777,
                "preferences": {
                    "property_type": ["apartment", "house"],
                    "purpose": "buy",
                    "budget_min": 8000000,
                    "budget_max": 15000000,
                    "bedrooms_min": 2,
                    "bedrooms_max": 4,
                    "area_min": 800,
                    "area_max": 1200,
                    "location_preference": ["Bandra West", "Juhu", "Andheri West"],
                    "max_distance_km": 15
                },
                "preferred_locations": ["Mumbai", "Bandra West", "Juhu"],
                "notification_settings": {
                    "email_notifications": True,
                    "push_notifications": True,
                    "sms_notifications": True
                },
                "privacy_settings": {
                    "profile_visibility": "friends",
                    "location_sharing": False
                },
                "profile_image_url": "https://api.dicebear.com/7.x/avataaars/svg?seed=Priya"
            }
        ]
        
        created_count = 0
        
        for i, user_data in enumerate(test_users[:count]):
            try:
                # Check if user already exists
                existing_user = await self.user_repo.get_by_field("email", user_data["email"])
                if existing_user:
                    self.logger.info(f"User {user_data['email']} already exists, skipping...")
                    continue
                
                # Create user
                user = await self.user_repo.create(user_data)
                created_count += 1
                
                self.logger.info(f"Created user: {user_data['full_name']} ({user_data['email']})")
                
            except Exception as e:
                self.logger.error(f"Failed to create user {user_data['email']}: {str(e)}")
                continue
        
        self.logger.info(f"Successfully created {created_count} users")
        return created_count
    
    async def clear_all(self) -> int:
        """Clear all test users"""
        try:
            # Delete test users by email pattern
            test_emails = ["testuser1@360ghar.com", "testuser2@360ghar.com"]
            deleted_count = 0
            
            for email in test_emails:
                deleted = await self.user_repo.delete_by_field("email", email)
                deleted_count += deleted
            
            self.logger.info(f"Deleted {deleted_count} test users")
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Failed to clear users: {str(e)}")
            return 0