"""AI Agent service package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.ai_agent.agent_service import PydanticAIAgentService
    from app.services.ai_agent.tools import AgentDeps

__all__ = ["PydanticAIAgentService", "AgentDeps", "get_agent_service"]

_service: Any | None = None


def __getattr__(name: str) -> Any:
    if name == "PydanticAIAgentService":
        from app.services.ai_agent.agent_service import PydanticAIAgentService

        return PydanticAIAgentService
    if name == "AgentDeps":
        from app.services.ai_agent.tools import AgentDeps

        return AgentDeps
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_agent_service() -> Any:
    """Return a singleton agent service instance."""
    global _service
    if _service is None:
        from app.services.ai_agent.agent_service import PydanticAIAgentService

        _service = PydanticAIAgentService()
    return _service
