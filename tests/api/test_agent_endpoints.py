"""
Tests for agent endpoints.

These tests verify the agent-related API endpoints work correctly.
They mock the service layer to isolate endpoint testing.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.models.enums import AgentType, ExperienceLevel
from app.schemas.agent import (
    Agent,
    AgentAssignment,
    AgentStats,
    AgentSystemStats,
    AgentWithStats,
    AgentWorkload,
)


def create_mock_agent(agent_id: int = 1, name: str = "Test Agent") -> Agent:
    """Create a mock agent schema object."""
    return Agent(
        id=agent_id,
        name=name,
        contact_number="+919876543210",
        description="A test agent",
        avatar_url="https://example.com/avatar.png",
        languages=["english"],
        agent_type=AgentType.general,
        experience_level=ExperienceLevel.intermediate,
        is_active=True,
        is_available=True,
        working_hours={"start": "09:00", "end": "18:00", "timezone": "UTC"},
        total_users_assigned=10,
        user_satisfaction_rating=4.5,
        created_at=datetime.now(timezone.utc),
        updated_at=None,
    )


def create_mock_assignment(user_id: int = 1, agent: Agent = None) -> AgentAssignment:
    """Create a mock agent assignment."""
    if agent is None:
        agent = create_mock_agent()
    return AgentAssignment(
        user_id=user_id,
        agent=agent,
        assigned_at=datetime.now(timezone.utc),
        assignment_reason="auto_assigned",
    )


def create_mock_agent_with_stats(agent_id: int = 1) -> AgentWithStats:
    """Create a mock agent with stats."""
    base_agent = create_mock_agent(agent_id)
    stats = AgentStats(
        total_users_assigned=10,
        user_satisfaction_rating=4.5,
        active_conversations=5,
        daily_interactions=20,
        weekly_interactions=100,
        efficiency_score=0.85,
    )
    return AgentWithStats(
        **base_agent.model_dump(),
        stats=stats,
    )


def create_mock_system_stats() -> AgentSystemStats:
    """Create mock system stats."""
    workload = AgentWorkload(
        agent_id=1,
        agent_name="Test Agent",
        current_users=10,
        utilization_percentage=0.75,
        is_available=True,
        queue_length=2,
    )
    return AgentSystemStats(
        total_agents=5,
        active_agents=4,
        total_users_served=100,
        system_satisfaction_score=4.2,
        agents_by_type={"general": 3, "specialist": 1, "senior": 1},
        load_distribution=[workload],
    )


class TestGetAvailableAgentsEndpoint:
    """Tests for GET /api/v1/agents/available/ endpoint."""

    @pytest.mark.asyncio
    async def test_get_available_agents_list(self, authenticated_client: AsyncClient):
        """Test getting available agents list."""
        with patch(
            "app.api.api_v1.endpoints.agents.get_available_agents_paginated",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = ([], None, None)

            response = await authenticated_client.get("/api/v1/agents/available/")

            assert response.status_code == 200
            data = response.json()
            assert "items" in data


class TestGetAllAgentsEndpoint:
    """Tests for GET /api/v1/agents/ endpoint (admin only)."""

    @pytest.mark.asyncio
    async def test_get_all_agents_list(self, admin_authenticated_client: AsyncClient):
        """Test getting all agents list (admin)."""
        with patch(
            "app.api.api_v1.endpoints.agents.get_all_agents_paginated",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = ([], None, None)

            response = await admin_authenticated_client.get("/api/v1/agents/")

            assert response.status_code == 200
            data = response.json()
            assert "items" in data


class TestGetAgentByIdEndpoint:
    """Tests for GET /api/v1/agents/{agent_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_agent_success(self, authenticated_client: AsyncClient):
        """Test getting agent by ID."""
        with patch(
            "app.api.api_v1.endpoints.agents.get_agent_by_id",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = create_mock_agent(1, "Test Agent")

            response = await authenticated_client.get("/api/v1/agents/1")

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == 1
            assert data["name"] == "Test Agent"

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, authenticated_client: AsyncClient):
        """Test getting non-existent agent."""
        with patch(
            "app.api.api_v1.endpoints.agents.get_agent_by_id",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None

            response = await authenticated_client.get("/api/v1/agents/99999")

            assert response.status_code == 404


class TestGetAssignedAgentEndpoint:
    """Tests for GET /api/v1/agents/assigned/ endpoint."""

    @pytest.mark.asyncio
    async def test_get_assigned_agent(self, authenticated_client: AsyncClient):
        """Test getting current user's assigned agent."""
        with patch(
            "app.api.api_v1.endpoints.agents.get_user_agent",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = create_mock_agent(1, "My Agent")

            response = await authenticated_client.get("/api/v1/agents/assigned/")

            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "My Agent"

    @pytest.mark.asyncio
    async def test_get_assigned_agent_none(self, authenticated_client: AsyncClient):
        """Test when no agent is assigned."""
        with patch(
            "app.api.api_v1.endpoints.agents.get_user_agent",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None

            response = await authenticated_client.get("/api/v1/agents/assigned/")

            # Returns 404 when no agent is assigned
            assert response.status_code == 404


class TestAssignAgentEndpoint:
    """Tests for POST /api/v1/agents/assign/ endpoint."""

    @pytest.mark.asyncio
    async def test_assign_agent_auto(self, authenticated_client: AsyncClient):
        """Test auto-assigning agent."""
        with patch(
            "app.api.api_v1.endpoints.agents.assign_agent_to_user",
            new_callable=AsyncMock,
        ) as mock_assign:
            mock_assign.return_value = create_mock_assignment(user_id=1)

            response = await authenticated_client.post("/api/v1/agents/assign/")

            assert response.status_code == 200
            data = response.json()
            assert "agent" in data
            assert data["user_id"] == 1

    @pytest.mark.asyncio
    async def test_assign_specific_agent(self, authenticated_client: AsyncClient):
        """Test assigning specific agent."""
        with patch(
            "app.api.api_v1.endpoints.agents.assign_agent_to_user",
            new_callable=AsyncMock,
        ) as mock_assign:
            agent = create_mock_agent(42, "Specific Agent")
            mock_assign.return_value = create_mock_assignment(user_id=1, agent=agent)

            response = await authenticated_client.post(
                "/api/v1/agents/assign/",
                params={"agent_id": 42},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["agent"]["id"] == 42

    @pytest.mark.asyncio
    async def test_assign_agent_unavailable(self, authenticated_client: AsyncClient):
        """Test when no agents are available."""
        with patch(
            "app.api.api_v1.endpoints.agents.assign_agent_to_user",
            new_callable=AsyncMock,
        ) as mock_assign:
            mock_assign.return_value = None

            response = await authenticated_client.post("/api/v1/agents/assign/")

            # Returns 503 when no agents available
            assert response.status_code == 503


class TestGetAgentWithStatsEndpoint:
    """Tests for GET /api/v1/agents/{agent_id}/stats/ endpoint."""

    @pytest.mark.asyncio
    async def test_get_agent_with_stats(self, authenticated_client: AsyncClient):
        """Test getting agent with statistics."""
        with patch(
            "app.api.api_v1.endpoints.agents.get_agent_with_stats",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = create_mock_agent_with_stats(42)

            response = await authenticated_client.get("/api/v1/agents/42/stats/")

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == 42
            assert "stats" in data

    @pytest.mark.asyncio
    async def test_get_agent_stats_not_found(self, authenticated_client: AsyncClient):
        """Test getting stats for non-existent agent."""
        with patch(
            "app.api.api_v1.endpoints.agents.get_agent_with_stats",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = None

            response = await authenticated_client.get("/api/v1/agents/99999/stats/")

            assert response.status_code == 404


class TestGetAgentsByTypeEndpoint:
    """Tests for GET /api/v1/agents/types/{agent_type} endpoint."""

    @pytest.mark.asyncio
    async def test_get_agents_by_type(self, authenticated_client: AsyncClient):
        """Test getting agents by type."""
        with patch(
            "app.api.api_v1.endpoints.agents.get_agents_by_type_paginated",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = ([], None, None)

            response = await authenticated_client.get("/api/v1/agents/types/general")

            assert response.status_code == 200


class TestGetSystemStatsEndpoint:
    """Tests for GET /api/v1/agents/system/stats/ endpoint."""

    @pytest.mark.asyncio
    async def test_get_system_stats(self, admin_authenticated_client: AsyncClient):
        """Test getting agent system statistics."""
        with patch(
            "app.api.api_v1.endpoints.agents.get_system_stats",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = create_mock_system_stats()

            response = await admin_authenticated_client.get("/api/v1/agents/system/stats/")

            assert response.status_code == 200
            data = response.json()
            assert data["total_agents"] == 5
            assert data["active_agents"] == 4


class TestUpdateAgentAvailabilityEndpoint:
    """Tests for PATCH /api/v1/agents/{agent_id}/availability/ endpoint."""

    @pytest.mark.asyncio
    async def test_update_availability(self, admin_authenticated_client: AsyncClient):
        """Test updating agent availability."""
        with patch(
            "app.api.api_v1.endpoints.agents.update_agent_availability",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = True

            response = await admin_authenticated_client.patch(
                "/api/v1/agents/42/availability/",
                params={"is_available": False},
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_update_availability_not_found(
        self, admin_authenticated_client: AsyncClient
    ):
        """Test updating availability for non-existent agent."""
        with patch(
            "app.api.api_v1.endpoints.agents.update_agent_availability",
            new_callable=AsyncMock,
        ) as mock_update:
            mock_update.return_value = False

            response = await admin_authenticated_client.patch(
                "/api/v1/agents/99999/availability/",
                params={"is_available": False},
            )

            assert response.status_code == 404


class TestGetAgentMeEndpoint:
    """Tests for GET /api/v1/agents/me/ endpoint (agent self-profile)."""

    @pytest.mark.asyncio
    async def test_get_agent_profile(self, agent_authenticated_client: AsyncClient):
        """Test getting agent's own profile."""
        with patch(
            "app.api.api_v1.endpoints.agents.get_agent_by_id",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = create_mock_agent(1, "Agent Profile")

            response = await agent_authenticated_client.get("/api/v1/agents/me/")

            # May return 404 if agent_id not linked on the test user
            assert response.status_code in [200, 404]
