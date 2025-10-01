"""Amenity data populator that loads predefined amenities from JSON."""
import json
from typing import Optional, List, Dict, Any
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.models.properties import Amenity
from .base import BasePopulator

class AmenityPopulator(BasePopulator):
    """Populates predefined amenities in the database from JSON seed data."""

    def __init__(self):
        super().__init__()

    @property
    def model_class(self):
        return Amenity

    @property
    def unique_fields(self) -> List[str]:
        return ['title']  # Amenities are unique by title

    def _default_amenities_path(self) -> str:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "data", "amenities.json")

    def _load_amenities_from_file(self, file_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """Load amenity definitions from JSON."""
        path = file_path or self._default_amenities_path()
        if not os.path.exists(path):
            raise FileNotFoundError(f"Amenity JSON not found at: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise ValueError("amenities.json must contain a list of amenity objects")
        return data

    async def populate_from_json(
        self,
        count: Optional[int] = None,
        file_path: Optional[str] = None,
    ) -> Dict[str, int]:
        """Create predefined amenities from JSON data with duplicate checking."""
        amenities_data = self._load_amenities_from_file(file_path)

        if count is not None:
            amenities_data = amenities_data[:count]

        # Filter out amenities without titles
        processed_data = []
        for amenity_data in amenities_data:
            title = amenity_data.get("title")
            if not title:
                self.logger.warning("Skipping amenity without a title in JSON data")
                continue
            processed_data.append(amenity_data)

        return await self.populate(processed_data, skip_existing=True)
