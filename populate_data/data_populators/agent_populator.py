"""
Agent data populator for testing
"""
from typing import Optional
import sys
import os
from sqlalchemy import select, delete

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.logging import get_logger
from app.models.models import Agent
from app.models.enums import AgentType, ExperienceLevel
from .base import BasePopulator

logger = get_logger(__name__)

class AgentPopulator(BasePopulator):
    """Populates test 360Ghar employee agents in the database"""
    
    def __init__(self):
        super().__init__()
    
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
                "description": "Expert property consultant specializing in Delhi NCR region with 5+ years of experience. Helps clients find their perfect home through personalized property recommendations.",
                "avatar_url": "https://api.dicebear.com/7.x/avataaars/svg?seed=ArjunSingh",
                "languages": ["english", "hindi", "punjabi"],
                "agent_type": AgentType.senior,
                "experience_level": ExperienceLevel.expert,
                "is_active": True,
                "is_available": True,
                "working_hours": {
                    "start": "09:00",
                    "end": "19:00", 
                    "timezone": "Asia/Kolkata",
                    "days": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
                },
                "total_users_assigned": 45,
                "user_satisfaction_rating": 4.8
            },
            {
                "name": "Sneha Reddy",
                "description": "Mumbai property specialist with deep knowledge of residential and commercial real estate. Expert in luxury properties and premium locations across Mumbai.",
                "avatar_url": "https://api.dicebear.com/7.x/avataaars/svg?seed=SnehaReddy",
                "languages": ["english", "hindi", "marathi", "telugu"],
                "agent_type": AgentType.senior,
                "experience_level": ExperienceLevel.expert,
                "is_active": True,
                "is_available": True,
                "working_hours": {
                    "start": "08:30",
                    "end": "18:30",
                    "timezone": "Asia/Kolkata", 
                    "days": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
                },
                "total_users_assigned": 38,
                "user_satisfaction_rating": 4.9
            }
        ]
        
        created_count = 0
        
        async with await self.get_db_session() as session:
            try:
                for i, agent_data in enumerate(test_agents[:count]):
                    try:
                        # Check if agent already exists by name
                        existing_agent = await session.execute(
                            select(Agent).where(Agent.name == agent_data["name"])
                        )
                        if existing_agent.scalar_one_or_none():
                            self.logger.info(f"Agent {agent_data['name']} already exists, skipping...")
                            continue
                        
                        # Create agent
                        agent = Agent(**agent_data)
                        session.add(agent)
                        await session.flush()  # Get the ID
                        created_count += 1
                        
                        self.logger.info(f"Created agent: {agent_data['name']}")
                        
                    except Exception as e:
                        self.logger.error(f"Failed to create agent {agent_data['name']}: {str(e)}")
                        continue
                
                await session.commit()
                self.logger.info(f"Successfully created {created_count} agents")
                
            except Exception as e:
                await session.rollback()
                self.logger.error(f"Failed to create agents: {str(e)}")
                raise
        
        return created_count
    
    async def clear_all(self) -> int:
        """Clear all test agents"""
        try:
            # Delete test agents by name
            test_names = ["Arjun Singh", "Sneha Reddy"]
            deleted_count = 0
            
            async with await self.get_db_session() as session:
                for name in test_names:
                    result = await session.execute(
                        delete(Agent).where(Agent.name == name)
                    )
                    deleted_count += result.rowcount
                
                await session.commit()
            
            self.logger.info(f"Deleted {deleted_count} test agents")
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Failed to clear agents: {str(e)}")
            return 0