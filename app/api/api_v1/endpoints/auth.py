from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.core.config import settings
from app.core.database import get_db
from app.core.security import verify_supabase_token
from app.core.supabase_client import get_supabase_client, get_supabase_admin_client
from app.models.user import User
from app.schemas.user import UserCreate, Token, User as UserSchema, UserLogin
from app.services.user import get_user_by_email, get_or_create_user_from_supabase, get_user_by_supabase_id

router = APIRouter()

async def get_current_user(authorization: str = Header(None), db: AsyncSession = Depends(get_db)):
    """Get current user from Supabase JWT token"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing"
        )
    
    # Extract token from "Bearer <token>" format
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication scheme"
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format"
        )
    
    # Verify token with Supabase
    supabase_user_data = verify_supabase_token(token)
    if not supabase_user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    
    # Get or create user in our database
    db_user = await get_or_create_user_from_supabase(db, supabase_user_data)
    return db_user

async def get_current_user_optional(
    authorization: str = Header(None), 
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Get current user if token is provided, otherwise return None"""
    if not authorization:
        return None
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            return None
    except ValueError:
        return None
    
    supabase_user_data = verify_supabase_token(token)
    if not supabase_user_data:
        return None
    
    db_user = await get_or_create_user_from_supabase(db, supabase_user_data)
    return db_user

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

@router.get("/me", response_model=UserSchema)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    """Get current user profile - requires valid Supabase token"""
    return current_user

@router.post("/sync")
async def sync_user_profile(current_user: User = Depends(get_current_active_user)):
    """Sync user profile with latest Supabase data"""
    return {"message": "Profile synced successfully", "user": current_user}

@router.get("/session")
async def check_session(authorization: str = Header(None)):
    """Check if current session is valid"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No session found"
        )
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid session format"
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session format"
        )
    
    supabase_user_data = verify_supabase_token(token)
    if not supabase_user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired"
        )
    
    return {
        "valid": True,
        "user_id": supabase_user_data["id"],
        "email": supabase_user_data["email"],
        "email_verified": supabase_user_data["email_verified"]
    }

@router.post("/login")
async def login(user_login: UserLogin, db: AsyncSession = Depends(get_db)):
    supabase = get_supabase_client()
    try:
        data = supabase.auth.sign_in_with_password({"email": user_login.email, "password": user_login.password})
        supabase_user_data = verify_supabase_token(data.session.access_token)
        db_user = await get_or_create_user_from_supabase(db, supabase_user_data)
        return {"access_token": data.session.access_token, "token_type": "bearer"}
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))