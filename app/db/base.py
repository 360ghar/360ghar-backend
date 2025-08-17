from typing import Dict, Any, List, Optional, Union, Type, TypeVar
from supabase import Client
from pydantic import BaseModel
import anyio
from enum import Enum
from app.core.supabase_client import (
    handle_supabase_error, 
    build_filters, 
    build_pagination, 
    build_sorting
)
from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar('T', bound=BaseModel)

 

class BaseRepository:
    """Base repository providing common CRUD operations using Supabase"""
    
    def __init__(self, client: Client, table_name: str):
        self.client = client
        self.table_name = table_name
        self.table = client.table(table_name)
    
    def _normalize_value(self, value: Any) -> Any:
        """Convert Enums to their primitive values; handle lists and nested dicts."""
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, list):
            return [self._normalize_value(item) for item in value]
        if isinstance(value, dict):
            return {k: self._normalize_value(v) for k, v in value.items()}
        return value
    
    def _normalize_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {k: self._normalize_value(v) for k, v in (data or {}).items()}
    
    def _normalize_enum_response(self, data: Any) -> Any:
        """Convert uppercase enum strings from database to lowercase for Pydantic validation"""
        if not data:
            return data
        
        # Define enum fields that need normalization
        enum_fields = {
            'property_type': {'HOUSE': 'house', 'APARTMENT': 'apartment', 'BUILDER_FLOOR': 'builder_floor', 'ROOM': 'room'},
            'purpose': {'BUY': 'buy', 'RENT': 'rent', 'SHORT_STAY': 'short_stay'},
            'status': {'AVAILABLE': 'available', 'SOLD': 'sold', 'RENTED': 'rented', 'UNDER_OFFER': 'under_offer', 'MAINTENANCE': 'maintenance'},
            'booking_status': {'PENDING': 'pending', 'CONFIRMED': 'confirmed', 'CHECKED_IN': 'checked_in', 'CHECKED_OUT': 'checked_out', 'CANCELLED': 'cancelled', 'COMPLETED': 'completed'},
            'payment_status': {'PENDING': 'pending', 'PARTIAL': 'partial', 'PAID': 'paid', 'REFUNDED': 'refunded', 'FAILED': 'failed'},
            'visit_status': {'SCHEDULED': 'scheduled', 'CONFIRMED': 'confirmed', 'COMPLETED': 'completed', 'CANCELLED': 'cancelled', 'RESCHEDULED': 'rescheduled'}
        }
        
        # Handle lists
        if isinstance(data, list):
            return [self._normalize_enum_response(item) for item in data]
        
        # Handle dictionaries
        if isinstance(data, dict):
            normalized = data.copy()
            for field, mapping in enum_fields.items():
                if field in normalized and normalized[field] is not None:
                    # Skip lists and other unhashable types
                    if not isinstance(normalized[field], (list, dict)) and normalized[field] in mapping:
                        normalized[field] = mapping[normalized[field]]
            
            # Convert features array to dict if needed for schema compatibility
            if 'features' in normalized and isinstance(normalized['features'], list):
                features_list = normalized['features']
                normalized['features'] = {feature: True for feature in features_list} if features_list else {}
            
            # Convert amenities array to dict if needed for schema compatibility  
            if 'amenities' in normalized and isinstance(normalized['amenities'], list):
                amenities_list = normalized['amenities']
                # Keep amenities as list since schema expects List[str]
                normalized['amenities'] = amenities_list
            
            # Recursively normalize nested objects
            for key, value in normalized.items():
                if isinstance(value, (dict, list)):
                    normalized[key] = self._normalize_enum_response(value)
            
            return normalized
        
        # Return as-is for primitive types
        return data
    
    async def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new record"""
        try:
            payload = self._normalize_payload(data)
            result = await anyio.to_thread.run_sync(
                lambda: self.table.insert(payload).execute()
            )
            if result.data:
                return result.data[0]
            raise ValueError("No data returned from insert operation")
        except Exception as e:
            logger.error(f"Failed to create record in {self.table_name}: {str(e)}")
            raise handle_supabase_error(e)
    
    async def get_by_id(
        self, 
        record_id: Union[int, str], 
        select: str = "*"
    ) -> Optional[Dict[str, Any]]:
        """Get a single record by ID"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: self.table.select(select).eq("id", record_id).limit(1).execute()
            )
            if result.data:
                return self._normalize_enum_response(result.data[0])
            return None
        except Exception as e:
            logger.error(f"Failed to get record {record_id} from {self.table_name}: {str(e)}")
            raise handle_supabase_error(e)
    
    async def get_by_field(
        self, 
        field: str, 
        value: Any, 
        select: str = "*"
    ) -> Optional[Dict[str, Any]]:
        """Get a single record by field value"""
        try:
            norm_value = self._normalize_value(value)
            result = await anyio.to_thread.run_sync(
                lambda: self.table.select(select).eq(field, norm_value).limit(1).execute()
            )
            if result.data:
                return self._normalize_enum_response(result.data[0])
            return None
        except Exception as e:
            logger.error(f"Failed to get record by {field}={value} from {self.table_name}: {str(e)}")
            raise handle_supabase_error(e)
    
    async def get_multi(
        self,
        *,
        filters: Optional[Dict[str, Any]] = None,
        select: str = "*",
        page: int = 1,
        limit: int = 20,
        sort_field: Optional[str] = None,
        sort_desc: bool = False
    ) -> Dict[str, Any]:
        """Get multiple records with filtering, pagination, and sorting"""
        try:
            def build_query():
                query = self.table.select(select, count="exact")
                
                # Apply filters
                if filters:
                    query = build_filters(query, filters)
                
                # Apply sorting
                if sort_field:
                    query = build_sorting(query, sort_field, sort_desc)
                
                # Apply pagination
                query = build_pagination(query, page, limit)
                
                return query.execute()
            
            result = await anyio.to_thread.run_sync(build_query)
            
            # Normalize enum values in all items
            normalized_items = [self._normalize_enum_response(item) for item in (result.data or [])]
            
            return {
                "items": normalized_items,
                "total": result.count or 0,
                "page": page,
                "limit": limit,
                "total_pages": ((result.count or 0) + limit - 1) // limit
            }
        except Exception as e:
            logger.error(f"Failed to get multiple records from {self.table_name}: {str(e)}")
            raise handle_supabase_error(e)
    
    async def update(
        self, 
        record_id: Union[int, str], 
        data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update a record by ID"""
        try:
            payload = self._normalize_payload(data)
            result = await anyio.to_thread.run_sync(
                lambda: self.table.update(payload).eq("id", record_id).execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to update record {record_id} in {self.table_name}: {str(e)}")
            raise handle_supabase_error(e)
    
    async def update_by_field(
        self, 
        field: str, 
        value: Any, 
        data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Update records by field value"""
        try:
            norm_value = self._normalize_value(value)
            payload = self._normalize_payload(data)
            result = await anyio.to_thread.run_sync(
                lambda: self.table.update(payload).eq(field, norm_value).execute()
            )
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to update records by {field}={value} in {self.table_name}: {str(e)}")
            raise handle_supabase_error(e)
    
    async def delete(self, record_id: Union[int, str]) -> bool:
        """Delete a record by ID"""
        try:
            result = await anyio.to_thread.run_sync(
                lambda: self.table.delete().eq("id", record_id).execute()
            )
            return len(result.data or []) > 0
        except Exception as e:
            logger.error(f"Failed to delete record {record_id} from {self.table_name}: {str(e)}")
            raise handle_supabase_error(e)
    
    async def delete_by_field(self, field: str, value: Any) -> int:
        """Delete records by field value and return count deleted"""
        try:
            norm_value = self._normalize_value(value)
            result = await anyio.to_thread.run_sync(
                lambda: self.table.delete().eq(field, norm_value).execute()
            )
            return len(result.data or [])
        except Exception as e:
            logger.error(f"Failed to delete records by {field}={value} from {self.table_name}: {str(e)}")
            raise handle_supabase_error(e)
    
    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """Count records with optional filtering"""
        try:
            def build_count_query():
                query = self.table.select("id", count="exact")
                
                if filters:
                    query = build_filters(query, filters)
                
                return query.limit(1).execute()
            
            result = await anyio.to_thread.run_sync(build_count_query)
            return result.count or 0
        except Exception as e:
            logger.error(f"Failed to count records in {self.table_name}: {str(e)}")
            raise handle_supabase_error(e)
    
    async def exists(self, field: str, value: Any) -> bool:
        """Check if a record exists with given field value"""
        try:
            norm_value = self._normalize_value(value)
            result = await anyio.to_thread.run_sync(
                lambda: self.table.select("id").eq(field, norm_value).limit(1).execute()
            )
            return len(result.data or []) > 0
        except Exception as e:
            logger.error(f"Failed to check existence in {self.table_name}: {str(e)}")
            raise handle_supabase_error(e)
    
    async def upsert(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert or update record"""
        try:
            payload = self._normalize_payload(data)
            result = await anyio.to_thread.run_sync(
                lambda: self.table.upsert(payload).execute()
            )
            if result.data:
                return result.data[0]
            raise ValueError("No data returned from upsert operation")
        except Exception as e:
            logger.error(f"Failed to upsert record in {self.table_name}: {str(e)}")
            raise handle_supabase_error(e)
    
    async def batch_insert(self, data_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Insert multiple records"""
        try:
            payload = [self._normalize_payload(item) for item in (data_list or [])]
            result = await anyio.to_thread.run_sync(
                lambda: self.table.insert(payload).execute()
            )
            return result.data or []
        except Exception as e:
            logger.error(f"Failed to batch insert in {self.table_name}: {str(e)}")
            raise handle_supabase_error(e)