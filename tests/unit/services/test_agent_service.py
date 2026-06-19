"""
Tests for agent service module.
"""


import pytest
from sqlalchemy.ext.asyncio import AsyncSession


class TestGetAllAgents:
    """Tests for get_all_agents function."""

    @pytest.mark.asyncio
    async def test_get_all_agents(self, db_session: AsyncSession, test_agents):
        """Test getting all agents."""
        from app.services.agent import get_all_agents

        result = await get_all_agents(db_session)

        assert len(result) >= len(test_agents)


class TestGetActiveAgents:
    """Tests for get_active_agents function."""

    @pytest.mark.asyncio
    async def test_get_active_agents(self, db_session: AsyncSession, test_agents):
        """Test getting only active agents."""
        from app.services.agent import get_active_agents

        result = await get_active_agents(db_session)

        for agent in result:
            assert agent.is_active is True


class TestGetAvailableAgents:
    """Tests for get_available_agents function."""

    @pytest.mark.asyncio
    async def test_get_available_agents(self, db_session: AsyncSession, test_agents):
        """Test getting available agents."""
        from app.services.agent import get_available_agents

        result = await get_available_agents(db_session)

        for agent in result:
            assert agent.is_active is True
            assert agent.is_available is True


class TestGetAgentById:
    """Tests for get_agent_by_id function."""

    @pytest.mark.asyncio
    async def test_get_agent_by_id_found(self, db_session: AsyncSession, test_agent):
        """Test getting agent by ID."""
        from app.services.agent import get_agent_by_id

        result = await get_agent_by_id(db_session, test_agent.id)

        assert result is not None
        assert result.id == test_agent.id

    @pytest.mark.asyncio
    async def test_get_agent_by_id_not_found(self, db_session: AsyncSession):
        """Test getting non-existent agent."""
        from app.services.agent import get_agent_by_id

        result = await get_agent_by_id(db_session, 99999)

        assert result is None


class TestCreateAgent:
    """Tests for create_agent function."""

    @pytest.mark.asyncio
    async def test_create_agent_success(self, db_session: AsyncSession, test_user):
        """Test successful agent creation."""
        from app.schemas.agent import AgentCreate
        from app.services.agent import create_agent

        agent_data = AgentCreate(
            user_id=test_user.id,
            name="New Agent",
            email="newagent@example.com",
            phone="+919876543210",
            agent_type="general",
        )

        result = await create_agent(db_session, agent_data)

        assert result is not None
        assert result.name == "New Agent"
        assert result.is_active is True
        assert result.is_available is True


class TestUpdateAgent:
    """Tests for update_agent function."""

    @pytest.mark.asyncio
    async def test_update_agent_success(self, db_session: AsyncSession, test_agent):
        """Test successful agent update."""
        from app.schemas.agent import AgentUpdate
        from app.services.agent import update_agent

        update_data = AgentUpdate(name="Updated Agent Name")

        result = await update_agent(db_session, test_agent.id, update_data)

        assert result is not None
        assert result.name == "Updated Agent Name"

    @pytest.mark.asyncio
    async def test_update_agent_not_found(self, db_session: AsyncSession):
        """Test updating non-existent agent."""
        from app.schemas.agent import AgentUpdate
        from app.services.agent import update_agent

        update_data = AgentUpdate(name="Updated Name")

        result = await update_agent(db_session, 99999, update_data)

        assert result is None


class TestDeleteAgent:
    """Tests for delete_agent function."""

    @pytest.mark.asyncio
    async def test_delete_agent_success(self, db_session: AsyncSession, test_agent):
        """Test soft deleting agent."""
        from app.services.agent import delete_agent

        result = await delete_agent(db_session, test_agent.id)

        assert result is True

        # Verify soft deleted
        await db_session.refresh(test_agent)
        assert test_agent.is_active is False

    @pytest.mark.asyncio
    async def test_delete_agent_not_found(self, db_session: AsyncSession):
        """Test deleting non-existent agent."""
        from app.services.agent import delete_agent

        result = await delete_agent(db_session, 99999)

        assert result is False


class TestGetUserAgent:
    """Tests for get_user_agent function."""

    @pytest.mark.asyncio
    async def test_get_user_agent_assigned(
        self,
        db_session: AsyncSession,
        test_user_with_agent,
    ):
        """Test getting agent for user with assigned agent."""
        from app.services.agent import get_user_agent

        result = await get_user_agent(db_session, test_user_with_agent.id, auto_assign=False)

        assert result is not None

    @pytest.mark.asyncio
    async def test_get_user_agent_no_assignment(
        self,
        db_session: AsyncSession,
        test_user,
    ):
        """Test getting agent for user without assignment."""
        from app.services.agent import get_user_agent

        # Disable auto-assign
        result = await get_user_agent(db_session, test_user.id, auto_assign=False)

        # User has no agent assigned and auto_assign=False, so result should be None
        assert result is None


class TestAssignAgentToUser:
    """Tests for assign_agent_to_user function."""

    @pytest.mark.asyncio
    async def test_auto_assign_agent(
        self,
        db_session: AsyncSession,
        test_user,
        test_agents,
    ):
        """Test auto-assigning agent to user."""
        from app.services.agent import assign_agent_to_user

        result = await assign_agent_to_user(db_session, test_user.id)

        assert result is not None
        assert result.agent is not None
        assert result.user_id == test_user.id

    @pytest.mark.asyncio
    async def test_assign_specific_agent(
        self,
        db_session: AsyncSession,
        test_user_2,
        test_agent,
    ):
        """Test assigning specific agent to user."""
        from app.services.agent import assign_agent_to_user

        result = await assign_agent_to_user(
            db_session,
            test_user_2.id,
            agent_id=test_agent.id,
        )

        assert result is not None
        assert result.agent.id == test_agent.id

    @pytest.mark.asyncio
    async def test_assign_agent_user_not_found(self, db_session: AsyncSession):
        """Test assigning agent to non-existent user."""
        from app.services.agent import assign_agent_to_user

        result = await assign_agent_to_user(db_session, 99999)

        assert result is None


class TestGetAgentWithStats:
    """Tests for get_agent_with_stats function."""

    @pytest.mark.asyncio
    async def test_get_agent_with_stats(self, db_session: AsyncSession, test_agent):
        """Test getting agent with statistics."""
        from app.services.agent import get_agent_with_stats

        result = await get_agent_with_stats(db_session, test_agent.id)

        assert result is not None
        assert result.stats is not None
        assert hasattr(result.stats, "total_users_assigned")
        assert hasattr(result.stats, "efficiency_score")


class TestUpdateAgentAvailability:
    """Tests for update_agent_availability function."""

    @pytest.mark.asyncio
    async def test_update_availability_success(self, db_session: AsyncSession, test_agent):
        """Test updating agent availability."""
        from app.services.agent import update_agent_availability

        result = await update_agent_availability(db_session, test_agent.id, False)

        assert result is True

        await db_session.refresh(test_agent)
        assert test_agent.is_available is False

    @pytest.mark.asyncio
    async def test_update_availability_not_found(self, db_session: AsyncSession):
        """Test updating availability for non-existent agent."""
        from app.services.agent import update_agent_availability

        result = await update_agent_availability(db_session, 99999, False)

        assert result is False


class TestGetWorkloadDistribution:
    """Tests for get_workload_distribution function."""

    @pytest.mark.asyncio
    async def test_get_workload_distribution(self, db_session: AsyncSession, test_agents):
        """Test getting workload distribution."""
        from app.services.agent import get_workload_distribution

        result = await get_workload_distribution(db_session)

        assert isinstance(result, list)
        for workload in result:
            assert hasattr(workload, "agent_id")
            assert hasattr(workload, "current_users")
            assert hasattr(workload, "utilization_percentage")


class TestGetSystemStats:
    """Tests for get_system_stats function."""

    @pytest.mark.asyncio
    async def test_get_system_stats(self, db_session: AsyncSession, test_agents):
        """Test getting system statistics."""
        from app.services.agent import get_system_stats

        result = await get_system_stats(db_session)

        assert result is not None
        assert hasattr(result, "total_agents")
        assert hasattr(result, "active_agents")
        assert hasattr(result, "total_users_served")
        assert hasattr(result, "system_satisfaction_score")


class TestAgentPagination:
    """Tests for paginated agent queries."""

    @pytest.mark.asyncio
    async def test_get_all_agents_paginated(self, db_session: AsyncSession, test_agents):
        """Test paginated agent listing."""
        from app.services.agent import get_all_agents_paginated

        rows, next_payload, count_total = await get_all_agents_paginated(
            db_session, cursor_payload={}, limit=10
        )

        assert isinstance(rows, list)
        assert next_payload is None or isinstance(next_payload, dict)
        assert count_total is None

    @pytest.mark.asyncio
    async def test_get_available_agents_paginated(self, db_session: AsyncSession, test_agents):
        """Test paginated available agents."""
        from app.services.agent import get_available_agents_paginated

        rows, next_payload, count_total = await get_available_agents_paginated(
            db_session, cursor_payload={}, limit=10
        )

        assert isinstance(rows, list)
        for agent in rows:
            assert agent.is_active is True
            assert agent.is_available is True
