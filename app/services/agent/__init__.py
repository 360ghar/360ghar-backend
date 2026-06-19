"""Agent service package — re-exports for backward compatibility."""

from app.services.agent.analytics import (
    get_agent_with_stats,
    get_system_stats,
    get_workload_distribution,
    get_workload_distribution_paginated,
)
from app.services.agent.crud import (
    assign_agent_to_user,
    create_agent,
    delete_agent,
    get_active_agents,
    get_agent_by_id,
    get_agents_by_specialization_paginated,
    get_agents_by_type,
    get_agents_by_type_paginated,
    get_all_agents,
    get_all_agents_paginated,
    get_available_agents,
    get_available_agents_paginated,
    get_user_agent,
    update_agent,
    update_agent_availability,
)
from app.services.agent.interactions import (
    get_daily_interactions,
    get_weekly_interactions,
)

__all__ = [
    # CRUD
    "get_all_agents",
    "get_active_agents",
    "get_available_agents",
    "get_agent_by_id",
    "create_agent",
    "update_agent",
    "delete_agent",
    "get_user_agent",
    "assign_agent_to_user",
    "get_agents_by_type",
    "update_agent_availability",
    "get_available_agents_paginated",
    "get_agents_by_type_paginated",
    "get_agents_by_specialization_paginated",
    "get_all_agents_paginated",
    # Interactions
    "get_daily_interactions",
    "get_weekly_interactions",
    # Analytics
    "get_agent_with_stats",
    "get_workload_distribution",
    "get_workload_distribution_paginated",
    "get_system_stats",
]
