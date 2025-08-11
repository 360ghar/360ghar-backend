#!/usr/bin/env python3
"""
Script to completely clear all data from the database
"""

from sqlalchemy import text
import logging
from data_populators.base import create_database_session
from app.core.logging import setup_logging
from app.models.booking import Booking
from app.models.visit import Visit
from app.models.user_interaction import UserSearchHistory, UserFavorite, UserSwipe
from app.models.property import PropertyImage, Property
from app.models.visit import RelationshipManager
from app.models.user import User

logger = logging.getLogger(__name__)


def clear_all_data():
    logger.info("Clearing ALL data from database")
    
    session = create_database_session()
    
    try:
        # Clear in proper order (reverse dependency)
        logger.info("Clearing bookings")
        session.query(Booking).delete()
        session.commit()
        
        logger.info("Clearing visits")
        session.query(Visit).delete()
        session.commit()
        
        logger.info("Clearing user interactions")
        session.query(UserSearchHistory).delete()
        session.query(UserFavorite).delete()
        session.query(UserSwipe).delete()
        session.commit()
        
        logger.info("Clearing property images")
        session.query(PropertyImage).delete()
        session.commit()
        
        logger.info("Clearing properties")
        session.query(Property).delete()
        session.commit()
        
        logger.info("Clearing relationship managers")
        session.query(RelationshipManager).delete()
        session.commit()
        
        logger.info("Clearing users")
        session.query(User).delete()
        session.commit()
        
        # Reset sequences (for PostgreSQL)
        logger.info("Resetting ID sequences")
        tables = ['users', 'properties', 'property_images', 'user_swipes', 'user_favorites', 
                 'user_search_history', 'visits', 'relationship_managers', 'bookings']
        
        for table in tables:
            session.execute(text(f"ALTER SEQUENCE {table}_id_seq RESTART WITH 1"))
        
        session.commit()
        logger.info("All data cleared successfully")
        
    except Exception as e:
        logging.getLogger(__name__).exception(f"Error clearing data: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    setup_logging()
    clear_all_data()