"""
User data populator for testing
"""
import uuid
from datetime import datetime, timezone, date
from typing import Optional
import sys
import os
from sqlalchemy import select, delete

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.logging import get_logger
from app.models.models import User
from .base import BasePopulator

logger = get_logger(__name__)

class UserPopulator(BasePopulator):
    """Populates test users in the database"""
    
    def __init__(self):
        super().__init__()
    
    async def populate(self, count: Optional[int] = 2) -> int:
        """
        Create test users
        
        Args:
            count: Number of users to create (default: 2)
            
        Returns:
            Number of users created
        """
        if count is None:
            count = 2
            
        self.logger.info(f"Creating {count} test users...")
        
        # Test user data
        test_users = [
            {
                "supabase_user_id": str(uuid.uuid4()),
                "email": "testuser1@360ghar.com",
                "full_name": "Raj Sharma",
                "phone": "+919876543210",
                "date_of_birth": date(1990, 5, 15),
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
                "supabase_user_id": str(uuid.uuid4()),
                "email": "testuser2@360ghar.com",
                "full_name": "Priya Patel",
                "phone": "+919876543211",
                "date_of_birth": date(1988, 8, 22),
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
        
        async with await self.get_db_session() as session:
            try:
                for i, user_data in enumerate(test_users[:count]):
                    try:
                        # Check if user already exists
                        existing_user = await session.execute(
                            select(User).where(User.email == user_data["email"])
                        )
                        if existing_user.scalar_one_or_none():
                            self.logger.info(f"User {user_data['email']} already exists, skipping...")
                            continue
                        
                        # Create user
                        user = User(**user_data)
                        session.add(user)
                        await session.flush()  # Get the ID
                        created_count += 1
                        
                        self.logger.info(f"Created user: {user_data['full_name']} ({user_data['email']})")
                        
                    except Exception as e:
                        self.logger.error(f"Failed to create user {user_data['email']}: {str(e)}")
                        continue
                
                await session.commit()
                self.logger.info(f"Successfully created {created_count} users")
                
            except Exception as e:
                await session.rollback()
                self.logger.error(f"Failed to create users: {str(e)}")
                raise
        
        return created_count
    
    async def clear_all(self) -> int:
        """Clear all test users"""
        try:
            # Delete test users by email pattern
            test_emails = ["testuser1@360ghar.com", "testuser2@360ghar.com"]
            deleted_count = 0
            
            async with await self.get_db_session() as session:
                for email in test_emails:
                    result = await session.execute(
                        delete(User).where(User.email == email)
                    )
                    deleted_count += result.rowcount
                
                await session.commit()
            
            self.logger.info(f"Deleted {deleted_count} test users")
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Failed to clear users: {str(e)}")
            return 0