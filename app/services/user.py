from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate

def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()

def get_user_by_id(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()

def get_user_by_supabase_id(db: Session, supabase_user_id: str):
    return db.query(User).filter(User.supabase_user_id == supabase_user_id).first()

def create_user_from_supabase(db: Session, supabase_user_data: Dict[str, Any]):
    """Create user in our database after Supabase authentication"""
    # Handle phone number properly - convert empty string to None to avoid unique constraint issues
    phone = supabase_user_data.get("phone")
    if phone == "" or phone is None:
        phone = None
    
    db_user = User(
        supabase_user_id=supabase_user_data["id"],
        email=supabase_user_data["email"],
        full_name=supabase_user_data.get("user_metadata", {}).get("full_name"),
        phone=phone,
        is_active=True,
        is_verified=supabase_user_data.get("email_verified", False)
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_or_create_user_from_supabase(db: Session, supabase_user_data: Dict[str, Any]):
    """Get existing user or create new one from Supabase data"""
    # First try to find by Supabase ID
    db_user = get_user_by_supabase_id(db, supabase_user_data["id"])
    
    if not db_user:
        # If not found, try by email
        db_user = get_user_by_email(db, supabase_user_data["email"])
        
        if db_user:
            # Update existing user with Supabase ID
            db_user.supabase_user_id = supabase_user_data["id"]
            db.commit()
            db.refresh(db_user)
        else:
            # Create new user
            db_user = create_user_from_supabase(db, supabase_user_data)
    
    return db_user

def update_user(db: Session, user_id: int, user_update: UserUpdate):
    db_user = get_user_by_id(db, user_id)
    if not db_user:
        return None
    
    update_data = user_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_user, field, value)
    
    db.commit()
    db.refresh(db_user)
    return db_user

def update_user_preferences(db: Session, user_id: int, preferences: dict):
    db_user = get_user_by_id(db, user_id)
    if db_user:
        db_user.preferences = preferences
        db.commit()
    return db_user

def update_user_location(db: Session, user_id: int, latitude: str, longitude: str):
    db_user = get_user_by_id(db, user_id)
    if db_user:
        db_user.current_latitude = latitude
        db_user.current_longitude = longitude
        db.commit()
    return db_user

def deactivate_user(db: Session, user_id: int):
    db_user = get_user_by_id(db, user_id)
    if db_user:
        db_user.is_active = False
        db.commit()
    return db_user

def verify_user(db: Session, user_id: int):
    db_user = get_user_by_id(db, user_id)
    if db_user:
        db_user.is_verified = True
        db.commit()
    return db_user