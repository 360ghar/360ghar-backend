"""User data populator that loads seed users from JSON."""
import json
import uuid
from datetime import date
from typing import Optional, List, Dict, Any
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.models.users import User
from .base import BasePopulator

class UserPopulator(BasePopulator):
    """Populates test users in the database from JSON seed data."""

    def __init__(self):
        super().__init__()

    @property
    def model_class(self):
        return User

    @property
    def unique_fields(self) -> List[str]:
        return ['email']  # Users are unique by email

    def _default_users_path(self) -> str:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "data", "users.json")

    def _load_users_from_file(self, file_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """Load user definitions from JSON."""
        path = file_path or self._default_users_path()
        if not os.path.exists(path):
            raise FileNotFoundError(f"User JSON not found at: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise ValueError("users.json must contain a list of user objects")
        return data

    def _prepare_user_payload(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Convert JSON payload into model friendly structure."""
        payload = dict(raw)

        supabase_id = payload.get("supabase_user_id")
        if not supabase_id:
            payload["supabase_user_id"] = str(uuid.uuid4())

        dob = payload.get("date_of_birth")
        if isinstance(dob, str):
            try:
                payload["date_of_birth"] = date.fromisoformat(dob)
            except ValueError:
                self.logger.warning(
                    f"Invalid date_of_birth '{dob}' for user {payload.get('email')}; using defaults"
                )
                payload["date_of_birth"] = date.today()
        elif not isinstance(dob, date):
            payload["date_of_birth"] = date.today()

        # Ensure JSON fields are dicts (None defaults to empty dict)
        for key in ("preferences", "notification_settings", "privacy_settings"):
            value = payload.get(key)
            if value is None:
                payload[key] = {}

        return payload

    async def populate_from_json(
        self,
        count: Optional[int] = None,
        file_path: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        Create test users from JSON seed data with duplicate checking.

        Args:
            count: Optional cap on number of users to create.
            file_path: Optional path to a custom users.json file.

        Returns:
            Dict with 'created' and 'skipped' counts.
        """
        users_data = self._load_users_from_file(file_path)

        if count is not None:
            users_data = users_data[:count]

        # Prepare user payloads
        processed_data = []
        for user_data in users_data:
            try:
                email = user_data.get("email")
                if not email:
                    self.logger.warning("Skipping user without an email in JSON data")
                    continue

                payload = self._prepare_user_payload(user_data)
                processed_data.append(payload)

            except Exception as exc:
                self.logger.error(f"Failed to prepare user payload: {exc}")
                continue

        return await self.populate(processed_data, skip_existing=True)
