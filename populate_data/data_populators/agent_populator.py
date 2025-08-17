"""
Agent data populator for testing
"""
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

class AgentPopulator(BasePopulator):
    """Populates test 360Ghar employee agents in the database"""
    
    def __init__(self):
        self.client = get_supabase_admin_client()
        self.agent_repo = BaseRepository(self.client, "agents")
        self.logger = get_logger(self.__class__.__name__)
    
    async def populate(self, count: Optional[int] = 2) -> int:
        """
        Create test agents
        
        Args:
            count: Number of agents to create (default: 2)
            
        Returns:
            Number of agents created
        """
        if count is None:
            count = 2
            
        self.logger.info(f"Creating {count} test agents...")
        
        # Test agent data
        test_agents = [
            {
                "name": "Arjun Singh",
                "agent_code": "AG_001_DELHI",
                "description": "Expert property consultant specializing in Delhi NCR region with 5+ years of experience. Helps clients find their perfect home through personalized property recommendations.",
                "avatar_url": "https://api.dicebear.com/7.x/avataaars/svg?seed=ArjunSingh",
                "personality_traits": {
                    "friendly": True,
                    "professional": True,
                    "knowledgeable": True,
                    "patient": True,
                    "responsive": True
                },
                "specializations": [
                    "residential_properties",
                    "luxury_apartments", 
                    "delhi_ncr_market",
                    "investment_advice",
                    "first_time_buyers"
                ],
                "languages": ["english", "hindi", "punjabi"],
                "agent_type": "senior",
                "experience_level": "senior",
                "max_concurrent_users": 75,
                "ai_model": "gpt-4",
                "system_prompt": "You are Arjun Singh, a senior property consultant at 360Ghar.com. You specialize in helping clients find the perfect home in Delhi NCR. Be friendly, knowledgeable, and always prioritize the client's needs and preferences.",
                "response_style": "professional_friendly",
                "is_active": True,
                "is_available": True,
                "working_hours": {
                    "start": "09:00",
                    "end": "19:00", 
                    "timezone": "Asia/Kolkata",
                    "days": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
                },
                "total_users_assigned": 45,
                "total_interactions": 1250,
                "average_response_time_seconds": 25,
                "user_satisfaction_rating": 4.8
            },
            {
                "name": "Sneha Reddy",
                "agent_code": "AG_002_MUMBAI",
                "description": "Mumbai property specialist with deep knowledge of residential and commercial real estate. Expert in luxury properties and premium locations across Mumbai.",
                "avatar_url": "https://api.dicebear.com/7.x/avataaars/svg?seed=SnehaReddy",
                "personality_traits": {
                    "empathetic": True,
                    "detail_oriented": True,
                    "market_savvy": True,
                    "communicative": True,
                    "trustworthy": True
                },
                "specializations": [
                    "mumbai_properties",
                    "luxury_homes",
                    "commercial_real_estate",
                    "property_investment",
                    "relocation_assistance"
                ],
                "languages": ["english", "hindi", "marathi", "telugu"],
                "agent_type": "senior",
                "experience_level": "expert",
                "max_concurrent_users": 60,
                "ai_model": "gpt-4",
                "system_prompt": "You are Sneha Reddy, an expert property consultant at 360Ghar.com specializing in Mumbai real estate. You have extensive knowledge of Mumbai's property market and excel at matching clients with their ideal properties.",
                "response_style": "consultative",
                "is_active": True,
                "is_available": True,
                "working_hours": {
                    "start": "08:30",
                    "end": "18:30",
                    "timezone": "Asia/Kolkata", 
                    "days": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
                },
                "total_users_assigned": 38,
                "total_interactions": 980,
                "average_response_time_seconds": 18,
                "user_satisfaction_rating": 4.9
            }
        ]
        
        created_count = 0
        
        for i, agent_data in enumerate(test_agents[:count]):
            try:
                # Check if agent already exists
                existing_agent = await self.agent_repo.get_by_field("agent_code", agent_data["agent_code"])
                if existing_agent:
                    self.logger.info(f"Agent {agent_data['agent_code']} already exists, skipping...")
                    continue
                
                # Create agent
                agent = await self.agent_repo.create(agent_data)
                created_count += 1
                
                self.logger.info(f"Created agent: {agent_data['name']} ({agent_data['agent_code']})")
                
            except Exception as e:
                self.logger.error(f"Failed to create agent {agent_data['agent_code']}: {str(e)}")
                continue
        
        self.logger.info(f"Successfully created {created_count} agents")
        return created_count
    
    async def clear_all(self) -> int:
        """Clear all test agents"""
        try:
            # Delete test agents by agent_code pattern
            test_codes = ["AG_001_DELHI", "AG_002_MUMBAI"]
            deleted_count = 0
            
            for code in test_codes:
                deleted = await self.agent_repo.delete_by_field("agent_code", code)
                deleted_count += deleted
            
            self.logger.info(f"Deleted {deleted_count} test agents")
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Failed to clear agents: {str(e)}")
            return 0