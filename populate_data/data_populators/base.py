"""
Base classes and utilities for data population with duplicate checking
"""
import asyncio
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Set
from dataclasses import dataclass
import sys
import os
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.logging import get_logger
from app.core.database import AsyncSessionLocal

logger = get_logger(__name__)

@dataclass
class LocationData:
    """Location-specific data and configurations"""
    name: str
    latitude: float
    longitude: float
    localities: List[str]
    price_per_sqft_range: tuple[int, int]  # (min, max) in local currency
    currency: str
    popular_amenities: List[str]
    builder_names: List[str]
    landmarks: List[str]

# User-provided constants
VIRTUAL_TOUR_URL = "https://kuula.co/share/collection/71284?logo=-1&card=1&info=0&fs=1&vr=1&thumbs=3&alpha=0.71"
MAIN_IMAGE_URL = "https://www.nobroker.in/blog/wp-content/uploads/2023/11/Victory-Valley.jpg"
OTHER_IMAGE_URL = "https://preview.redd.it/tallest-building-in-gurgaon-v0-z90z4alcfn0b1.jpg"

# Location configurations
LOCATIONS = {
    "us": LocationData(
        name="San Francisco",
        latitude=37.785834,
        longitude=-122.406417,
        localities=[
            "SOMA", "Mission District", "Castro", "Nob Hill", "Pacific Heights",
            "Richmond", "Sunset", "Haight-Ashbury", "Marina", "Financial District",
            "Chinatown", "North Beach", "Presidio", "Potrero Hill", "Bernal Heights"
        ],
        price_per_sqft_range=(800, 1500),  # USD per sqft
        currency="USD",
        popular_amenities=[
            "Fitness Center", "Rooftop Deck", "Concierge", "Parking", "In-unit Laundry",
            "Doorman", "Pet Spa", "Business Center", "Storage", "Bike Storage"
        ],
        builder_names=[
            "Lennar", "KB Home", "D.R. Horton", "Pulte Group", "NVR Inc",
            "Toll Brothers", "Ryan Homes", "Meritage Homes", "Taylor Morrison"
        ],
        landmarks=[
            "Near BART Station", "Near Golden Gate Park", "Near Financial District",
            "Near Union Square", "Near Crissy Field", "Near Mission Dolores Park"
        ]
    ),
    "mumbai": LocationData(
        name="Mumbai",
        latitude=19.076,
        longitude=72.8777,
        localities=[
            "Bandra West", "Juhu", "Andheri West", "Powai", "Lower Parel",
            "Worli", "Malad West", "Goregaon West", "Versova", "Khar West",
            "Santa Cruz West", "Vile Parle West", "Borivali West", "Kandivali West", "Lokhandwala"
        ],
        price_per_sqft_range=(15000, 40000),  # INR per sqft
        currency="INR",
        popular_amenities=[
            "Swimming Pool", "Gym", "Club House", "Security", "Power Backup",
            "Lift", "Garden", "Children's Play Area", "CCTV", "Intercom"
        ],
        builder_names=[
            "Godrej Properties", "Lodha Group", "Oberoi Realty", "Hiranandani Group",
            "Kalpataru Limited", "Runwal Group", "Raheja Universal", "Sunteck Realty"
        ],
        landmarks=[
            "Near Mumbai Airport", "Near Bandra-Kurla Complex", "Near Powai Lake",
            "Near Phoenix Mills", "Near Palladium Mall", "Near Western Express Highway"
        ]
    ),
    "gurgaon": LocationData(
        name="Gurgaon",
        latitude=28.446400,
        longitude=77.011711,
        localities=[
            "DLF Phase 1", "DLF Phase 2", "DLF Phase 3", "DLF Phase 4", "DLF Phase 5",
            "Sector 28", "Sector 29", "Sector 43", "Sector 45", "Sector 46",
            "Sohna Road", "Golf Course Road", "MG Road", "Cyber City", "Udyog Vihar",
            "Sushant Lok", "South City", "Ardee City", "Vatika City", "Nirvana Country"
        ],
        price_per_sqft_range=(8000, 15000),  # INR per sqft
        currency="INR",
        popular_amenities=[
            "Swimming Pool", "Gym", "Parking", "Security", "Power Backup", "Lift", "Garden",
            "Clubhouse", "Play Area", "CCTV", "Intercom", "Fire Safety", "Water Supply"
        ],
        builder_names=[
            "DLF Limited", "Unitech Group", "Ansal API", "Raheja Developers",
            "M3M India", "Godrej Properties", "Experion Developers", "Vatika Group"
        ],
        landmarks=[
            "Near Metro Station", "Near DLF CyberHub", "Near Ambience Mall",
            "Near Medanta Hospital", "Near Rapid Metro", "Near Golf Course"
        ]
    ),
    "dabra": LocationData(
        name="Dabra",
        latitude=25.8863596,
        longitude=78.3388375,
        localities=[
            "Civil Lines", "Sadar Bazar", "Sikandra Rao", "Nandanpura", "Orchha Gate",
            "Medical College Area", "Bundelkhand University", "Gwalior Road", "Kanpur Road",
            "Laxmi Puram", "Prem Nagar", "Shastri Nagar", "Vijay Nagar", "Rajgarh"
        ],
        price_per_sqft_range=(2500, 8000),  # INR per sqft
        currency="INR",
        popular_amenities=[
            "Swimming Pool", "Gym", "Parking", "Security", "Power Backup", "Lift", "Garden",
            "Clubhouse", "Play Area", "CCTV", "Intercom", "Water Supply", "Fire Safety"
        ],
        builder_names=[
            "Bundelkhand Builders", "Jhansi Realty", "Orchha Developers", "Sipri Construction",
            "Civil Lines Group", "Gwalior Properties", "Nandanpura Builders", "Rajgarh Realty"
        ],
        landmarks=[
            "Near Jhansi Fort", "Near Bundelkhand University", "Near Medical College",
            "Near Railway Station", "Near Rani Lakshmibai Park", "Near City Mall"
        ]
    )
}

class BasePopulator(ABC):
    """Base class for all data populators with duplicate checking"""

    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

    async def get_db_session(self) -> AsyncSession:
        """Get a database session"""
        return AsyncSessionLocal()

    @property
    @abstractmethod
    def model_class(self):
        """Return the SQLAlchemy model class for this populator"""
        pass

    @property
    @abstractmethod
    def unique_fields(self) -> List[str]:
        """
        Return list of field names that uniquely identify a record.
        For single field uniqueness: ['field_name']
        For composite uniqueness: ['field1', 'field2']
        For no uniqueness constraint: [] (will always create new records)
        """
        pass

    async def _record_exists(self, session: AsyncSession, data: Dict[str, Any]) -> bool:
        """
        Check if a record already exists based on unique fields

        Args:
            session: Database session
            data: Record data dictionary

        Returns:
            True if record exists, False otherwise
        """
        if not self.unique_fields:
            # No uniqueness constraint - always allow creation
            return False

        # Build where clause for unique field check
        where_conditions = []
        for field in self.unique_fields:
            if field in data:
                value = data[field]
                where_conditions.append(getattr(self.model_class, field) == value)

        if not where_conditions:
            # No unique field values provided - allow creation
            return False

        stmt = select(self.model_class).where(and_(*where_conditions))
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        return existing is not None

    async def _create_record(self, session: AsyncSession, data: Dict[str, Any]) -> bool:
        """
        Create a single record if it doesn't already exist

        Args:
            session: Database session
            data: Record data dictionary

        Returns:
            True if record was created, False if it already existed
        """
        if await self._record_exists(session, data):
            # Extract unique field values for logging
            unique_values = {field: data.get(field) for field in self.unique_fields if field in data}
            self.logger.debug(f"Record already exists with unique fields: {unique_values}")
            return False

        # Create new record
        record = self.model_class(**data)
        session.add(record)
        await session.flush()  # Get ID without committing

        # Log creation
        unique_values = {field: getattr(record, field) for field in self.unique_fields if hasattr(record, field)}
        self.logger.debug(f"Created new record with unique fields: {unique_values}")

        return True

    async def populate(
        self,
        data_list: List[Dict[str, Any]],
        skip_existing: bool = True
    ) -> Dict[str, int]:
        """
        Populate data for this entity type with duplicate checking

        Args:
            data_list: List of record data dictionaries
            skip_existing: If True, skip records that already exist

        Returns:
            Dict with 'created' and 'skipped' counts
        """
        created_count = 0
        skipped_count = 0

        self.logger.info(f"Processing {len(data_list)} records for {self.__class__.__name__}")

        async with await self.get_db_session() as session:
            try:
                for data in data_list:
                    if skip_existing and await self._record_exists(session, data):
                        skipped_count += 1
                        continue

                    try:
                        if await self._create_record(session, data):
                            created_count += 1
                        else:
                            skipped_count += 1
                    except Exception as exc:
                        self.logger.error(f"Failed to create record: {exc}")
                        continue

                    # Commit in batches to avoid memory issues
                    if (created_count + skipped_count) % 50 == 0:
                        await session.commit()

                await session.commit()
                self.logger.info(f"Population complete: {created_count} created, {skipped_count} skipped")

            except Exception as exc:
                await session.rollback()
                self.logger.error(f"Population failed: {exc}")
                raise

        return {"created": created_count, "skipped": skipped_count}

    async def clear_all(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """
        Clear all records for this entity type

        Args:
            filters: Optional filters to limit deletion (e.g., {'is_test_data': True})

        Returns:
            Number of records deleted
        """
        self.logger.info(f"Clearing all records for {self.__class__.__name__}")

        async with await self.get_db_session() as session:
            try:
                stmt = delete(self.model_class)
                if filters:
                    for field, value in filters.items():
                        stmt = stmt.where(getattr(self.model_class, field) == value)

                result = await session.execute(stmt)
                deleted_count = result.rowcount or 0

                await session.commit()
                self.logger.info(f"Cleared {deleted_count} records")

                return deleted_count

            except Exception as exc:
                await session.rollback()
                self.logger.error(f"Clear failed: {exc}")
                raise

    def log_progress(self, current: int, total: int, entity_name: str):
        """Log progress of data creation"""
        if current % max(1, total // 10) == 0 or current == total:
            percentage = (current / total) * 100
            self.logger.info(f"Processed {current}/{total} {entity_name} ({percentage:.1f}%)")

    # Legacy method for backward compatibility
    async def populate_legacy(self, count: Optional[int] = None) -> int:
        """
        Legacy populate method - override in subclasses if needed
        """
        raise NotImplementedError("Use populate() method with data_list parameter")