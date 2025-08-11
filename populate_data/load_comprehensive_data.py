#!/usr/bin/env python3
"""
Comprehensive Data Population System for 360Ghar Application

This script orchestrates the creation of realistic test data across all models
with proper dependency management and comprehensive coverage of edge cases.

Features:
- Multi-location property generation (US, Mumbai, Gurgaon)
- Realistic user interactions and behavior patterns
- Complete relationship management between entities
- Edge case coverage for all business scenarios
- Configurable data volumes and distributions
"""

import sys
import time
import logging
from datetime import datetime
from typing import Optional
logger = logging.getLogger(__name__)
from sqlalchemy.exc import SQLAlchemyError
from app.core.logging import setup_logging

from app.models.base import Base
from app.core.database import engine
from data_populators.base import create_database_session, get_default_config, DataConfig
from data_populators.user_populator import UserPopulator
from data_populators.property_populator import PropertyPopulator
from data_populators.interaction_populator import InteractionPopulator
from data_populators.visit_populator import VisitPopulator
from data_populators.booking_populator import BookingPopulator


class ComprehensiveDataLoader:
    """Main orchestrator for comprehensive data population"""
    
    def __init__(self, config: Optional[DataConfig] = None, clear_existing: bool = True):
        self.config = config or get_default_config()
        self.clear_existing = clear_existing
        self.session = None
        
        # Population modules
        self.user_populator = None
        self.property_populator = None
        self.interaction_populator = None
        self.visit_populator = None
        self.booking_populator = None
        
        # Data storage
        self.created_data = {}
        
    def initialize_database(self):
        """Initialize database and create tables if needed"""
        logger.info("Initializing database")
        
        try:
            # Create all tables if they don't exist
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables ready")
            
            # Create database session
            self.session = create_database_session()
            logger.info("Database session established")
            
            # Initialize populators
            self.user_populator = UserPopulator(self.session, self.config)
            self.property_populator = PropertyPopulator(self.session, self.config)
            self.interaction_populator = InteractionPopulator(self.session, self.config)
            self.visit_populator = VisitPopulator(self.session, self.config)
            self.booking_populator = BookingPopulator(self.session, self.config)
            
            logger.info("Data populators initialized")
            
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise
    
    def clear_existing_data(self):
        """Clear all existing data in proper order (respecting foreign key constraints)"""
        if not self.clear_existing:
            logger.info("Skipping data clearing (clear_existing=False)")
            return
        
        logger.info("Clearing existing data")
        
        try:
            # Clear in reverse dependency order
            self.booking_populator.clear_existing_data()
            self.visit_populator.clear_existing_data()
            self.interaction_populator.clear_existing_data()
            self.property_populator.clear_existing_data()
            self.user_populator.clear_existing_data()
            
            logger.info("Existing data cleared successfully")
            
        except Exception as e:
            logger.warning(f"Error clearing existing data: {e}. This may be expected if tables don't exist yet")
    
    def populate_users_and_managers(self):
        """Populate users and relationship managers"""
        logger.info("Phase 1: users and relationship managers")
        
        try:
            # Create main user first
            main_user = self.user_populator.create_main_user()
            
            # Create additional diverse users
            additional_users = self.user_populator.create_diverse_users(self.config.users_count - 1)
            all_users = [main_user] + additional_users
            
            # Create relationship managers
            relationship_managers = self.user_populator.create_relationship_managers()
            
            # Store created data
            self.created_data['users'] = all_users
            self.created_data['relationship_managers'] = relationship_managers
            
            logger.info(
                "Phase 1 summary",
                extra={
                    "total_users": len(all_users),
                    "main_user": getattr(main_user, "email", None),
                    "relationship_managers": len(relationship_managers),
                },
            )
            
        except Exception as e:
            logger.error(f"Error in Phase 1: {e}")
            raise
    
    def populate_properties(self):
        """Populate properties across all locations"""
        logger.info("Phase 2: properties across locations")
        
        try:
            properties = self.property_populator.create_properties_all_locations()
            
            # Store created data
            self.created_data['properties'] = properties
            
            # Analyze property distribution
            location_counts = {}
            type_counts = {}
            purpose_counts = {}
            
            for prop in properties:
                # Count by location
                location_counts[prop.city] = location_counts.get(prop.city, 0) + 1
                
                # Count by type
                type_counts[prop.property_type.value] = type_counts.get(prop.property_type.value, 0) + 1
                
                # Count by purpose
                purpose_counts[prop.purpose.value] = purpose_counts.get(prop.purpose.value, 0) + 1
            
            logger.info(
                "Phase 2 summary",
                extra={
                    "total_properties": len(properties),
                    "by_location": dict(location_counts),
                    "by_type": dict(type_counts),
                    "by_purpose": dict(purpose_counts),
                },
            )
            
        except Exception as e:
            logger.error(f"Error in Phase 2: {e}")
            raise
    
    def populate_user_interactions(self):
        """Populate user interactions (swipes, favorites, searches)"""
        logger.info("Phase 3: user interactions")
        
        try:
            users = self.created_data['users']
            properties = self.created_data['properties']
            
            # Create swipes
            swipes = self.interaction_populator.create_user_swipes(users, properties)
            
            # Create favorites (based on liked swipes)
            favorites = self.interaction_populator.create_user_favorites(users, properties)
            
            # Create search history
            searches = self.interaction_populator.create_search_history(users)
            
            # Store created data
            self.created_data['swipes'] = swipes
            self.created_data['favorites'] = favorites
            self.created_data['searches'] = searches
            
            # Calculate interaction statistics
            total_likes = sum(1 for s in swipes if s.is_liked)
            like_rate = (total_likes / len(swipes)) * 100 if swipes else 0
            
            logger.info(
                "Phase 3 summary",
                extra={
                    "total_swipes": len(swipes),
                    "like_rate": round(like_rate, 2),
                    "total_favorites": len(favorites),
                    "search_records": len(searches),
                },
            )
            
        except Exception as e:
            logger.error(f"Error in Phase 3: {e}")
            raise
    
    def populate_visits(self):
        """Populate property visits"""
        logger.info("Phase 4: property visits")
        
        try:
            users = self.created_data['users']
            properties = self.created_data['properties']
            relationship_managers = self.created_data['relationship_managers']
            favorites = self.created_data['favorites']
            
            visits = self.visit_populator.create_property_visits(
                users, properties, relationship_managers, favorites
            )
            
            # Store created data
            self.created_data['visits'] = visits
            
            # Analyze visit statistics
            status_counts = {}
            for visit in visits:
                status_counts[visit.status.value] = status_counts.get(visit.status.value, 0) + 1
            
            logger.info(
                "Phase 4 summary",
                extra={
                    "total_visits": len(visits),
                    "by_status": dict(status_counts),
                },
            )
            
        except Exception as e:
            logger.error(f"Error in Phase 4: {e}")
            raise
    
    def populate_bookings(self):
        """Populate short-stay bookings"""
        logger.info("Phase 5: short-stay bookings")
        
        try:
            users = self.created_data['users']
            properties = self.created_data['properties']
            
            bookings = self.booking_populator.create_bookings(users, properties)
            
            # Store created data
            self.created_data['bookings'] = bookings
            
            # Analyze booking statistics
            booking_status_counts = {}
            payment_status_counts = {}
            total_revenue = 0
            
            for booking in bookings:
                # Count by booking status
                booking_status_counts[booking.booking_status.value] = \
                    booking_status_counts.get(booking.booking_status.value, 0) + 1
                
                # Count by payment status
                payment_status_counts[booking.payment_status.value] = \
                    payment_status_counts.get(booking.payment_status.value, 0) + 1
                
                # Calculate total revenue
                if booking.payment_status.value in ['paid', 'partial']:
                    total_revenue += booking.total_amount
            
            logger.info(
                "Phase 5 summary",
                extra={
                    "total_bookings": len(bookings),
                    "by_booking_status": dict(booking_status_counts),
                    "by_payment_status": dict(payment_status_counts),
                    "total_revenue": round(total_revenue, 2),
                },
            )
            
        except Exception as e:
            logger.error(f"Error in Phase 5: {e}")
            raise
    
    def generate_final_report(self):
        """Generate comprehensive final report"""
        logger.info("Data population completed")
        
        # Calculate totals
        total_records = sum(len(data) if isinstance(data, list) else 1 
                          for data in self.created_data.values())
        
        logger.info("Totals", extra={"total_records": int(total_records)})
        
        # Coverage is deterministic based on generation; skip verbose prints
        
        location_counts = {}
        for prop in self.created_data.get('properties', []):
            location_counts[prop.city] = location_counts.get(prop.city, 0) + 1
        logger.info("Location coverage", extra={"by_city": location_counts})
    
    def cleanup(self):
        """Clean up resources"""
        if self.session:
            self.session.close()
            logger.info("Database session closed")
    
    def run(self):
        """Execute the complete data population process"""
        start_time = time.time()
        
        try:
            logger.info(
                "Starting data population",
                extra={
                    "start_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "users": self.config.users_count,
                    "properties_total": self.config.properties_per_location * 3,
                },
            )
            
            # Execute all phases
            self.initialize_database()
            self.clear_existing_data()
            self.populate_users_and_managers()
            self.populate_properties()
            
            # Generate final report
            self.generate_final_report()
            
            execution_time = time.time() - start_time
            logger.info("Execution complete", extra={"seconds": round(execution_time, 2)})
            
        except SQLAlchemyError as e:
            logger.error(f"Database error: {e}")
            sys.exit(1)
            
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            sys.exit(1)
            
        finally:
            self.cleanup()


def main():
    """Main entry point with configuration options"""
    import argparse
    setup_logging()
    
    parser = argparse.ArgumentParser(description='Comprehensive Data Population for 360Ghar')
    parser.add_argument('--users', type=int, default=100, help='Number of users to create')
    parser.add_argument('--properties-per-location', type=int, default=700, 
                       help='Number of properties per location')
    parser.add_argument('--no-clear', action='store_true', 
                       help='Do not clear existing data before population')
    parser.add_argument('--quick', action='store_true',
                       help='Quick mode with reduced data volumes')
    
    args = parser.parse_args()
    
    # Configure based on arguments
    if args.quick:
        config = DataConfig(
            users_count=20,
            properties_per_location=50,
            relationship_managers_count=5
        )
        logging.getLogger(__name__).info("Quick mode: reduced data volumes")
    else:
        config = DataConfig(
            users_count=args.users,
            properties_per_location=args.properties_per_location
        )
    
    # Create and run data loader
    loader = ComprehensiveDataLoader(
        config=config,
        clear_existing=not args.no_clear
    )
    
    loader.run()


if __name__ == "__main__":
    main()