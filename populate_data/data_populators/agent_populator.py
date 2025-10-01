"""Agent data populator that loads seed data from JSON."""
import json
from typing import Optional, List, Dict, Any
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.models.agents import Agent
from app.models.enums import AgentType, ExperienceLevel
from .base import BasePopulator

class AgentPopulator(BasePopulator):
    """Populates 360Ghar agents in the database from JSON seed data."""

    def __init__(self):
        super().__init__()

    @property
    def model_class(self):
        return Agent

    @property
    def unique_fields(self) -> List[str]:
        return ['name']  # Agents are unique by name

    def _default_agents_path(self) -> str:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "data", "agents.json")

    def _load_agents_from_file(self, file_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """Load agent definitions from JSON."""
        path = file_path or self._default_agents_path()
        if not os.path.exists(path):
            raise FileNotFoundError(f"Agent JSON not found at: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise ValueError("agents.json must contain a list of agent objects")
        return data

    def _prepare_agent_payload(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Convert JSON payload into model friendly structure."""
        payload = dict(raw)

        agent_type_value = payload.get("agent_type")
        if agent_type_value is not None:
            payload["agent_type"] = AgentType(agent_type_value)

        experience_value = payload.get("experience_level")
        if experience_value is not None:
            payload["experience_level"] = ExperienceLevel(experience_value)

        return payload

    async def populate_from_json(
        self,
        count: Optional[int] = None,
        file_path: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        Create test agents from JSON seed data with duplicate checking.

        Args:
            count: Optional cap on number of agents to create.
            file_path: Optional path to a custom agents.json file.

        Returns:
            Dict with 'created' and 'skipped' counts.
        """
        agents_data = self._load_agents_from_file(file_path)

        if count is not None:
            agents_data = agents_data[:count]

        # Prepare agent payloads
        processed_data = []
        for agent_data in agents_data:
            try:
                name = agent_data.get("name")
                if not name:
                    self.logger.warning("Skipping agent without a name in JSON data")
                    continue

                payload = self._prepare_agent_payload(agent_data)
                processed_data.append(payload)

            except Exception as exc:
                self.logger.error(f"Failed to prepare agent payload: {exc}")
                continue

        return await self.populate(processed_data, skip_existing=True)
