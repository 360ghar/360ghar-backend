from fastapi import APIRouter, Depends, HTTPException, status, Header
from supabase import Client
from typing import Optional, Dict, Any
from app.core.config import settings
from app.core.supabase_client import get_supabase_dependency, get_supabase_client
from app.core.security import verify_supabase_token
from app.schemas.user import UserCreate, Token, User as UserSchema, UserLogin
from app.services.user import get_user_by_email, get_or_create_user_from_supabase, get_user_by_supabase_id
from app.core.logging import get_logger
import anyio

logger = get_logger(__name__)

router = APIRouter()

async def get_current_user(authorization: str = Header(None), supabase: Client = Depends(get_supabase_dependency)) -> UserSchema:
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
    supabase_user_data = await verify_supabase_token(token)
    if not supabase_user_data:
        logger.warning("Failed token verification", extra={"token_prefix": token[:10] + "..."})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    
    # Get or create user in our database
    db_user = await get_or_create_user_from_supabase(supabase, supabase_user_data)
    logger.debug("User authenticated successfully", extra={"user_id": db_user.id, "email": db_user.email})
    
    return db_user

async def get_current_user_optional(
    authorization: str = Header(None),
    supabase: Client = Depends(get_supabase_dependency)
) -> Optional[UserSchema]:
    """Get current user if token is provided, otherwise return None"""
    if not authorization:
        return None
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            return None
    except ValueError:
        return None
    
    try:
        supabase_user_data = await verify_supabase_token(token)
        if not supabase_user_data:
            return None
        
        db_user = await get_or_create_user_from_supabase(supabase, supabase_user_data)
        return db_user
    except Exception:
        return None

async def get_current_active_user(current_user: UserSchema = Depends(get_current_user)) -> UserSchema:
    """Get current active user"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user




@router.post("/login")
async def login(user_login: UserLogin, supabase: Client = Depends(get_supabase_dependency)):
    """Login user with email and password via Supabase Auth"""
    try:
        # Use Supabase client directly for authentication
        supabase_client = get_supabase_client()
        data = await anyio.to_thread.run_sync(
            lambda: supabase_client.auth.sign_in_with_password({
                "email": user_login.email, 
                "password": user_login.password
            })
        )
        
        # Verify the token and sync user data
        supabase_user_data = await verify_supabase_token(data.session.access_token)
        db_user = await get_or_create_user_from_supabase(supabase, supabase_user_data)
        
        return {
            "access_token": data.session.access_token,
            "token_type": "bearer",
            "user": db_user
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")

@router.post("/register")
async def register(user_data: UserCreate, supabase: Client = Depends(get_supabase_dependency)):
    """Register a new user via Supabase Auth"""
    try:
        supabase_client = get_supabase_client()
        data = await anyio.to_thread.run_sync(
            lambda: supabase_client.auth.sign_up({
                "email": user_data.email,
                "password": user_data.password,
                "options": {
                    "data": {
                        "full_name": user_data.full_name,
                        "phone": user_data.phone
                    }
                }
            })
        )
        
        if data.user:
            # Check if user already exists first
            existing_user = await get_user_by_email(supabase, data.user.email)
            
            if existing_user:
                # User already exists, just return success
                db_user = existing_user
            else:
                # Create user in our database
                supabase_user_data = {
                    "id": data.user.id,
                    "email": data.user.email,
                    "email_verified": getattr(data.user, 'email_verified', False),
                    "user_metadata": data.user.user_metadata or {}
                }
                
                db_user = await get_or_create_user_from_supabase(supabase, supabase_user_data)
            
            return {
                "message": "User registered successfully",
                "user": db_user,
                "access_token": data.session.access_token if data.session else None,
                "token_type": "bearer" if data.session else None
            }
        else:
            raise HTTPException(status_code=400, detail="Registration failed")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Registration failed: {str(e)}")


@router.post("/refresh")
async def refresh_token(authorization: str = Header(None)):
    """Refresh access token"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing"
        )
    
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
    
    # For now, just validate the token
    # In a production environment, you might want to implement token refresh logic
    supabase_user_data = await verify_supabase_token(token)
    if not supabase_user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    
    return {
        "access_token": token,  # In practice, this would be a new token
        "token_type": "bearer"
    }