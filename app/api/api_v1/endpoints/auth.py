from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.auth import get_supabase_auth_client, verify_supabase_token
from app.core.logging import get_logger
from app.schemas.user import UserCreate, UserLogin, User as UserSchema
from app.services.user import get_or_create_user_from_supabase
import anyio
from typing import Optional

router = APIRouter()
logger = get_logger(__name__)

async def get_current_user(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db)
) -> UserSchema:
    """Get current user from token"""
    if not authorization:
        logger.debug("Authorization header missing")
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            logger.warning("Invalid authentication scheme")
            raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    except ValueError:
        logger.warning("Invalid authorization header format")
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    try:
        supabase_user_data = await verify_supabase_token(token)
        if not supabase_user_data:
            logger.warning("Invalid or expired token")
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        
        db_user = await get_or_create_user_from_supabase(db, supabase_user_data)
        logger.debug(f"User authenticated successfully: {db_user.id}")
        return db_user
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=401, detail="Authentication failed")

async def get_current_active_user(current_user: UserSchema = Depends(get_current_user)) -> UserSchema:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_user_optional(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db)
) -> Optional[UserSchema]:
    if not authorization:
        return None
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            return None
        
        supabase_user_data = await verify_supabase_token(token)
        if supabase_user_data:
            return await get_or_create_user_from_supabase(db, supabase_user_data)
    except Exception:
        pass
    
    return None

@router.post("/login")
async def login(user_login: UserLogin, db: AsyncSession = Depends(get_db)):
    """Login with Supabase Auth"""
    try:
        supabase = get_supabase_auth_client()
        data = await anyio.to_thread.run_sync(
            lambda: supabase.auth.sign_in_with_password({
                "email": user_login.email,
                "password": user_login.password
            })
        )
        
        supabase_user_data = await verify_supabase_token(data.session.access_token)
        db_user = await get_or_create_user_from_supabase(db, supabase_user_data)
        
        return {
            "access_token": data.session.access_token,
            "token_type": "bearer",
            "user": db_user
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")

@router.post("/register")
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register via Supabase Auth"""
    try:
        supabase = get_supabase_auth_client()
        data = await anyio.to_thread.run_sync(
            lambda: supabase.auth.sign_up({
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
            supabase_user_data = {
                "id": data.user.id,
                "email": data.user.email,
                "user_metadata": data.user.user_metadata or {}
            }
            
            db_user = await get_or_create_user_from_supabase(db, supabase_user_data)
            
            return {
                "message": "User registered successfully",
                "user": db_user,
                "access_token": data.session.access_token if data.session else None
            }
        else:
            raise HTTPException(status_code=400, detail="Registration failed")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Registration failed: {str(e)}")