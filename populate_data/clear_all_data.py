#!/usr/bin/env python3
"""
Script to completely clear all data from the database
"""

from sqlalchemy import text
from data_populators.base import create_database_session
from app.models.booking import Booking
from app.models.visit import Visit
from app.models.user_interaction import UserSearchHistory, UserFavorite, UserSwipe
from app.models.property import PropertyImage, Property
from app.models.visit import RelationshipManager
from app.models.user import User

def clear_all_data():
    print("🧹 Clearing ALL data from database...")
    
    session = create_database_session()
    
    try:
        # Clear in proper order (reverse dependency)
        print("  Clearing bookings...")
        session.query(Booking).delete()
        session.commit()
        
        print("  Clearing visits...")
        session.query(Visit).delete()
        session.commit()
        
        print("  Clearing user interactions...")
        session.query(UserSearchHistory).delete()
        session.query(UserFavorite).delete()
        session.query(UserSwipe).delete()
        session.commit()
        
        print("  Clearing property images...")
        session.query(PropertyImage).delete()
        session.commit()
        
        print("  Clearing properties...")
        session.query(Property).delete()
        session.commit()
        
        print("  Clearing relationship managers...")
        session.query(RelationshipManager).delete()
        session.commit()
        
        print("  Clearing users...")
        session.query(User).delete()
        session.commit()
        
        # Reset sequences (for PostgreSQL)
        print("  Resetting ID sequences...")
        tables = ['users', 'properties', 'property_images', 'user_swipes', 'user_favorites', 
                 'user_search_history', 'visits', 'relationship_managers', 'bookings']
        
        for table in tables:
            session.execute(text(f"ALTER SEQUENCE {table}_id_seq RESTART WITH 1"))
        
        session.commit()
        print("✅ All data cleared successfully!")
        
    except Exception as e:
        print(f"❌ Error clearing data: {e}")
        session.rollback()
        import traceback
        traceback.print_exc()
    finally:
        session.close()

if __name__ == "__main__":
    clear_all_data()