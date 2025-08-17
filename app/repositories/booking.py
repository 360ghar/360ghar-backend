from typing import List, Optional, Dict, Any
from supabase import Client
from app.db.base import BaseRepository
from app.db.types import BookingDB
from app.schemas.booking import BookingCreate, BookingUpdate
from app.core.supabase_client import execute_rpc
import anyio
from datetime import datetime
from app.core.logging import get_logger

logger = get_logger(__name__)

class BookingRepository(BaseRepository):
    """Repository for booking operations using Supabase"""
    
    def __init__(self, client: Client):
        super().__init__(client, "bookings")
    
    async def create_booking(self, booking_data: BookingCreate) -> BookingDB:
        """Create a new booking"""
        data = booking_data.dict(exclude_unset=True)
        return await self.create(data)
    
    async def get_booking_by_reference(self, booking_reference: str) -> Optional[BookingDB]:
        """Get booking by reference number"""
        return await self.get_by_field("booking_reference", booking_reference)
    
    async def get_user_bookings(
        self, 
        user_id: int, 
        page: int = 1, 
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get bookings for a user"""
        return await self.get_multi(
            filters={"user_id": user_id},
            select="*, properties(*)",
            page=page,
            limit=limit,
            sort_field="created_at",
            sort_desc=True
        )
    
    async def get_property_bookings(
        self, 
        property_id: int, 
        page: int = 1, 
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get bookings for a property"""
        return await self.get_multi(
            filters={"property_id": property_id},
            select="*, users(*)",
            page=page,
            limit=limit,
            sort_field="check_in_date"
        )
    
    async def check_availability(
        self, 
        property_id: int, 
        check_in: str, 
        check_out: str
    ) -> bool:
        """Check if property is available for given dates"""
        try:
            result = await execute_rpc(
                self.client, 
                "check_booking_availability", 
                {
                    "p_property_id": property_id,
                    "p_check_in_date": check_in,
                    "p_check_out_date": check_out
                }
            )
            # Function returns boolean, client SDK wraps in data; normalize to bool
            if isinstance(result, list):
                return bool(result[0]) if result else False
            return bool(result)
        except Exception as e:
            logger.error(f"Failed to check booking availability via RPC: {str(e)}")
            logger.warning("check_booking_availability RPC function may not be deployed to Supabase")
            # Return False to be safe when availability check fails
            return False
    
    async def update_booking_status(
        self, 
        booking_id: int, 
        status: str
    ) -> Optional[BookingDB]:
        """Update booking status"""
        return await self.update(booking_id, {"booking_status": status})
    
    async def update_payment_status(
        self, 
        booking_id: int, 
        status: str
    ) -> Optional[BookingDB]:
        """Update payment status"""
        return await self.update(booking_id, {"payment_status": status})
    
    async def cancel_booking(
        self, 
        booking_id: int, 
        reason: str
    ) -> Optional[BookingDB]:
        """Cancel a booking"""
        # Set timestamp via database NOW() using RPC-free approach: rely on trigger to update updated_at
        return await self.update(booking_id, {
            "booking_status": "cancelled",
            "cancellation_reason": reason,
            "cancellation_date": None
        })
    
    async def calculate_pricing(
        self, 
        property_id: int, 
        check_in: str, 
        check_out: str, 
        guests: int = 1
    ) -> Dict[str, Any]:
        """Calculate booking pricing using database function"""
        try:
            result = await execute_rpc(
                self.client,
                "calculate_booking_pricing",
                {
                    "p_property_id": property_id,
                    "p_check_in_date": check_in,
                    "p_check_out_date": check_out,
                    "p_guests": guests
                }
            )
            
            if result and len(result) > 0:
                pricing = result[0]
                return {
                    "property_id": property_id,
                    "nights": (datetime.fromisoformat(check_out.replace('Z', '+00:00')) - 
                             datetime.fromisoformat(check_in.replace('Z', '+00:00'))).days,
                    "base_amount": pricing.get("base_amount"),
                    "taxes_amount": pricing.get("taxes_amount"),
                    "service_charges": pricing.get("service_charges"),
                    "discount_amount": pricing.get("discount_amount"),
                    "total_amount": pricing.get("total_amount"),
                    "daily_rate": pricing.get("daily_rate")
                }
        except Exception as e:
            logger.error(f"Failed to calculate pricing via RPC: {str(e)}")
        
        # Fallback calculation
        try:
            nights = (datetime.fromisoformat(check_out.replace('Z', '+00:00')) - 
                     datetime.fromisoformat(check_in.replace('Z', '+00:00'))).days
            
            # Get property daily rate
            property_result = await anyio.to_thread.run_sync(
                lambda: self.client.table("properties").select("daily_rate").eq("id", property_id).limit(1).execute()
            )
            
            daily_rate = 100.0  # Default
            if property_result.data:
                daily_rate = property_result.data[0].get("daily_rate", 100.0)
            
            base_amount = daily_rate * nights
            taxes = base_amount * 0.12  # 12% tax
            service_charges = base_amount * 0.05  # 5% service
            total = base_amount + taxes + service_charges
            
            return {
                "property_id": property_id,
                "nights": nights,
                "base_amount": base_amount,
                "taxes_amount": taxes,
                "service_charges": service_charges,
                "discount_amount": 0.0,
                "total_amount": total,
                "daily_rate": daily_rate
            }
        except Exception as fallback_e:
            logger.error(f"Fallback pricing calculation failed: {str(fallback_e)}")
            # Return minimal fallback
            return {
                "property_id": property_id,
                "nights": 1,
                "base_amount": 100.0,
                "taxes_amount": 12.0,
                "service_charges": 5.0,
                "discount_amount": 0.0,
                "total_amount": 117.0,
                "daily_rate": 100.0
            }