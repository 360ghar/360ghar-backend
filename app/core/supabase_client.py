from supabase import create_client, Client
from typing import Dict, Any, Optional
from enum import Enum
import anyio
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Global client instances for connection reuse
_supabase_client: Optional[Client] = None
_supabase_admin_client: Optional[Client] = None

def get_supabase_client() -> Client:
    """Get Supabase client for regular operations (anon key)"""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return _supabase_client

def get_supabase_admin_client() -> Client:
    """Get Supabase admin client for privileged operations (service role key)"""
    global _supabase_admin_client
    if _supabase_admin_client is None:
        _supabase_admin_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SECRET_KEY)
    return _supabase_admin_client

def get_supabase_dependency() -> Client:
    """FastAPI dependency to get a Supabase client instance (service role by default)."""
    return get_supabase_admin_client()

def get_supabase_admin_dependency() -> Client:
    """FastAPI dependency to get a Supabase admin client instance"""
    return get_supabase_admin_client()

 

class SupabaseError(Exception):
    """Custom exception for Supabase-related errors"""
    def __init__(self, message: str, status_code: int = 500, details: Dict[str, Any] = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

def handle_supabase_error(error: Exception) -> SupabaseError:
    """Convert Supabase errors to custom exceptions with proper HTTP status codes"""
    error_msg = str(error)
    
    # Map common Supabase/PostgreSQL errors to HTTP status codes
    if "duplicate key" in error_msg.lower():
        return SupabaseError("Resource already exists", 409, {"type": "duplicate_key"})
    elif "foreign key" in error_msg.lower():
        return SupabaseError("Referenced resource not found", 404, {"type": "foreign_key"})
    elif "not found" in error_msg.lower() or "no rows" in error_msg.lower():
        return SupabaseError("Resource not found", 404, {"type": "not_found"})
    elif "permission denied" in error_msg.lower() or "unauthorized" in error_msg.lower():
        return SupabaseError("Permission denied - check authentication and RLS policies", 403, {"type": "permission_denied"})
    elif "invalid input" in error_msg.lower() or "check constraint" in error_msg.lower():
        return SupabaseError("Invalid input data", 422, {"type": "validation_error"})
    elif "jwt" in error_msg.lower() or "token" in error_msg.lower():
        return SupabaseError("Authentication token invalid or expired", 401, {"type": "auth_error"})
    elif "connection" in error_msg.lower() or "network" in error_msg.lower():
        return SupabaseError("Database connection failed", 503, {"type": "connection_error"})
    else:
        logger.error(f"Unhandled Supabase error: {error_msg}")
        return SupabaseError("Database operation failed", 500, {"type": "unknown", "original": error_msg})

async def execute_rpc(
    client: Client, 
    function_name: str, 
    params: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Execute RPC function with error handling"""
    try:
        result = await anyio.to_thread.run_sync(
            lambda: client.rpc(function_name, params or {}).execute()
        )
        return result.data
    except Exception as e:
        raise handle_supabase_error(e)

async def execute_query(query_builder, table: str = None) -> Dict[str, Any]:
    """Execute query with error handling and logging"""
    try:
        result = await anyio.to_thread.run_sync(lambda: query_builder.execute())
        return result
    except Exception as e:
        if table:
            logger.error(f"Query failed on table '{table}': {str(e)}")
        else:
            logger.error(f"Query failed: {str(e)}")
        raise handle_supabase_error(e)

def build_filters(query_builder, filters: Dict[str, Any]):
    """Apply filters to Supabase query builder"""
    enum_like_fields = {
        "property_type",
        "purpose",
        "status",
        "booking_status",
        "payment_status",
        "visit_status",
    }
    for field, value in filters.items():
        if value is None:
            continue
            
        # Normalize Enum values to their underlying string values
        if isinstance(value, Enum):
            value = value.value

        if isinstance(value, list):
            # Convert list of Enums (or mixed) to raw values
            normalized_list = [item.value if isinstance(item, Enum) else item for item in value]
            if normalized_list:  # Only apply filter if list is not empty
                if field in enum_like_fields:
                    # Cast enum columns to text for filtering to avoid enum type issues
                    quoted = ",".join([f'"{str(v)}"' for v in normalized_list])
                    query_builder = query_builder.filter(f"{field}::text", "in", f"({quoted})")
                else:
                    query_builder = query_builder.in_(field, normalized_list)
        elif isinstance(value, dict):
            # Handle range filters like {"min": 100, "max": 500}
            if "min" in value:
                query_builder = query_builder.gte(field, value["min"])
            if "max" in value:
                query_builder = query_builder.lte(field, value["max"])
        else:
            if field in enum_like_fields:
                query_builder = query_builder.filter(f"{field}::text", "eq", str(value))
            else:
                query_builder = query_builder.eq(field, value)
    
    return query_builder

def build_pagination(query_builder, page: int, limit: int):
    """Apply pagination to Supabase query builder"""
    start = (page - 1) * limit
    end = start + limit - 1
    return query_builder.range(start, end)

def build_sorting(query_builder, sort_field: str, sort_desc: bool = False):
    """Apply sorting to Supabase query builder"""
    return query_builder.order(sort_field, desc=sort_desc)

 

async def batch_execute(
    client: Client,
    operations: list
) -> list:
    """Execute multiple operations in batch for better performance"""
    try:
        results = await anyio.to_thread.run_sync(
            lambda: [op() for op in operations]
        )
        return results
    except Exception as e:
        raise handle_supabase_error(e)