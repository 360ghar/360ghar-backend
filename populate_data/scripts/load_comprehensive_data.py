#!/usr/bin/env python3
"""
Comprehensive data population script for 360Ghar backend testing

This script populates the database with sample data for testing:
- 1-2 test users
- 1-2 test agents
- Core amenity definitions
- 1000 properties across different locations
- FAQ entries for the help centre
- Sets up agent assignments for users

Usage:
    python populate_data/load_comprehensive_data.py
    python populate_data/load_comprehensive_data.py --quick  # Reduced data for faster testing
    python populate_data/load_comprehensive_data.py --clear  # Clear existing data first
"""

import asyncio
import argparse
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.logging import setup_logging, get_logger
from app.core.database import AsyncSessionLocal
from app.models.users import User
from app.models.agents import Agent
from sqlalchemy import select
from populate_data.data_populators.user_populator import UserPopulator
from populate_data.data_populators.agent_populator import AgentPopulator
from populate_data.data_populators.amenity_populator import AmenityPopulator
from populate_data.data_populators.property_populator import PropertyPopulator
from populate_data.data_populators.faq_populator import FAQPopulator
from populate_data.data_populators.page_populator import PagePopulator

# Configure logging
setup_logging()
logger = get_logger(__name__)

class DataLoader:
    """Main data loading coordinator"""

    def __init__(self):
        # Initialize populators
        self.user_populator = UserPopulator()
        self.agent_populator = AgentPopulator()
        self.amenity_populator = AmenityPopulator()
        self.property_populator = PropertyPopulator()
        self.faq_populator = FAQPopulator()
        self.page_populator = PagePopulator()
    
    async def clear_all_data(self):
        """Clear all test data from database"""
        logger.info("Clearing all test data...")

        try:
            # Clear in reverse dependency order
            cleared_properties = await self.property_populator.clear_all()
            cleared_users = await self.user_populator.clear_all()
            cleared_agents = await self.agent_populator.clear_all()
            cleared_amenities = await self.amenity_populator.clear_all()
            cleared_faqs = await self.faq_populator.clear_all()
            cleared_pages = await self.page_populator.clear_all()

            logger.info(
                "Cleared: %s properties, %s users, %s agents, %s amenities, %s FAQs, %s pages",
                cleared_properties,
                cleared_users,
                cleared_agents,
                cleared_amenities,
                cleared_faqs,
                cleared_pages,
            )

        except Exception as e:
            logger.error(f"Failed to clear data: {str(e)}")
            raise
    
    async def assign_agents_to_users(self):
        """Assign agents to users for testing"""
        try:
            logger.info("Assigning agents to users...")
            
            async with AsyncSessionLocal() as session:
                # Get all test users
                users_result = await session.execute(select(User))
                users = users_result.scalars().all()
                
                # Get all agents
                agents_result = await session.execute(select(Agent))
                agents = agents_result.scalars().all()
                
                if not agents:
                    logger.warning("No agents found to assign")
                    return
                
                # Assign agents to users in round-robin fashion
                for i, user in enumerate(users):
                    if user.agent_id is None:  # Only assign if not already assigned
                        agent = agents[i % len(agents)]
                        
                        # Update user with agent assignment
                        user.agent_id = agent.id
                        
                        # Update agent statistics
                        agent.total_users_assigned += 1
                        
                        logger.info(f"Assigned agent {agent.name} to user {user.full_name}")
                
                await session.commit()
            
        except Exception as e:
            logger.error(f"Failed to assign agents: {str(e)}")
            raise
    
    async def load_data(self, quick_mode: bool = False):
        """Load all test data"""
        start_time = datetime.now()
        logger.info(f"Starting data population {'(quick mode)' if quick_mode else '(full mode)'}...")
        
        try:
            # Determine counts based on mode
            if quick_mode:
                user_count = 2
                agent_count = 2
                properties_per_location = 17  # ~50 total for quick testing
            else:
                user_count = 2
                agent_count = 2
                properties_per_location = 100  # 100 properties per location
            
            # Step 1: Create agents first (users reference agents)
            logger.info("Step 1: Creating agents...")
            agent_result = await self.agent_populator.populate_from_json(agent_count)
            created_agents = agent_result["created"]
            skipped_agents = agent_result["skipped"]

            # Step 2: Create users
            logger.info("Step 2: Creating users...")
            user_result = await self.user_populator.populate_from_json(user_count)
            created_users = user_result["created"]
            skipped_users = user_result["skipped"]

            # Step 3: Create amenities (properties reference amenities)
            logger.info("Step 3: Creating amenities...")
            amenity_result = await self.amenity_populator.populate_from_json()
            created_amenities = amenity_result["created"]
            skipped_amenities = amenity_result["skipped"]

            # Step 4: Create properties
            logger.info("Step 4: Creating properties...")
            property_result = await self.property_populator.populate_generated(properties_per_location=properties_per_location)
            created_properties = property_result["created"]
            skipped_properties = property_result["skipped"]

            # Step 5: Assign agents to users
            logger.info("Step 5: Assigning agents to users...")
            await self.assign_agents_to_users()

            # Step 6: Create FAQs
            logger.info("Step 6: Creating FAQs...")
            faq_result = await self.faq_populator.populate_from_json(update_existing=True)
            created_faqs = faq_result.get("created", faq_result.get("updated", 0))
            skipped_faqs = faq_result.get("skipped", 0)

            # Step 7: Create Pages
            logger.info("Step 7: Creating pages...")
            page_result = await self.page_populator.populate_from_json(update_existing=True)
            created_pages = page_result.get("created", page_result.get("updated", 0))
            skipped_pages = page_result.get("skipped", 0)
            
            # Summary
            end_time = datetime.now()
            duration = end_time - start_time
            
            logger.info("=" * 60)
            logger.info("DATA POPULATION COMPLETE")
            logger.info("=" * 60)
            logger.info(f"Agents: {created_agents} created, {skipped_agents} skipped")
            logger.info(f"Users: {created_users} created, {skipped_users} skipped")
            logger.info(f"Amenities: {created_amenities} created, {skipped_amenities} skipped")
            logger.info(f"Properties: {created_properties} created, {skipped_properties} skipped")
            logger.info(f"FAQs: {created_faqs} created/updated, {skipped_faqs} skipped")
            logger.info(f"Pages: {created_pages} created/updated, {skipped_pages} skipped")
            logger.info(f"Duration: {duration.total_seconds():.2f} seconds")
            logger.info("=" * 60)
            
            # Test data overview
            logger.info("\nTEST DATA OVERVIEW:")
            logger.info("-" * 30)
            logger.info("Test Users:")
            if created_users > 0:
                logger.info("- testuser1@360ghar.com (Raj Sharma) - Prefers Gurgaon rentals")
                logger.info("- testuser2@360ghar.com (Priya Patel) - Looking to buy in Mumbai")
            else:
                logger.info("- None created (requires real Supabase Auth users)")
                logger.info("- Create users via Supabase Dashboard or Auth API first")
            logger.info("\nTest Agents:")
            logger.info("- AG_001_DELHI (Arjun Singh) - Delhi NCR specialist")
            logger.info("- AG_002_MUMBAI (Sneha Reddy) - Mumbai expert")
            logger.info(f"\nProperties: {created_properties} across San Francisco, Mumbai, and Gurgaon")
            logger.info("\nNext Steps:")
            logger.info("1. Start the API server: python run.py")
            logger.info("2. Test user login with the test accounts")
            logger.info("3. Test property discovery and swipe functionality")
            logger.info("4. Test agent assignment and interactions")
            
        except Exception as e:
            logger.error(f"Data population failed: {str(e)}")
            raise

async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Populate 360Ghar database with test data")
    parser.add_argument("--quick", action="store_true", help="Quick mode with reduced data")
    parser.add_argument("--clear", action="store_true", help="Clear existing test data first")
    
    args = parser.parse_args()
    
    loader = DataLoader()
    
    try:
        if args.clear:
            await loader.clear_all_data()
            logger.info("Data cleared successfully")
            return
        
        await loader.load_data(quick_mode=args.quick)
        logger.info("Data population completed successfully!")
        
    except Exception as e:
        logger.error(f"Data population failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
