# Agent

Agents are the human intermediaries between property seekers and listings. They schedule visits, respond to user questions, and accumulate satisfaction ratings. The Agent primitive is intentionally lean: it captures who the agent is and how busy they are, leaving the matching logic to the visit scheduling flow.

Active contributors: Saksham, Ravi

## Model

File: `app/models/agents.py`

The `Agent` table is small but indexed for load-balancing queries. Key columns:

- `name`, `contact_number`, `description`, `avatar_url` - profile fields surfaced in the agent directory
- `languages` - JSON list of supported languages, used to match non-English speakers
- `agent_type` - `AgentType` enum (`general`, `specialist`, `senior`). Drives assignment priority.
- `experience_level` - `ExperienceLevel` enum (`beginner`, `intermediate`, `expert`)
- `is_active` - whether the agent can be assigned new leads at all
- `is_available` - real-time availability flag, toggled by the visit assignment flow
- `working_hours` - JSON dict of day-of-week to time windows
- `total_users_assigned` - denormalized counter used as the load-balancing tiebreaker
- `user_satisfaction_rating` - rolling average of `AgentInteraction.user_satisfaction` (1-5)
- `is_seed_data` - marks demo agents

## Relationships

- `User` - one-to-many. A user may be linked to one agent for the duration of an engagement.
- `Visit` - one-to-many. Visits are the primary workload unit; each visit optionally carries an `agent_id`.
- `AgentInteraction` - one-to-many. Every chat, call, and email between an agent and a user is logged with `response_time_seconds` and `user_satisfaction`. This table feeds the satisfaction rating.

## Load balancing

When a visit is scheduled, the service layer picks an agent by:

1. Filter to `is_active = true` and `is_available = true`.
2. Join to `User` and count live assigned users per agent (`count(User.id)`).
3. Sort by user count ascending (least-loaded first), limit 1.

The `working_hours` column and `user_satisfaction_rating` exist on the model but are not currently used in the assignment query. There is no dedicated `app/services/agent.py` file; assignment logic lives in `app/services/agent/crud.py` (`assign_agent_to_user`) and the agents REST endpoint module (`app/api/api_v1/endpoints/agents.py`).

## REST surface

The `/api/v1/agents` router exposes the agent directory, profile details, and interaction history. Agent tools also surface through the admin MCP server (`/mcp-admin`) under the `agent_*` prefix - see [features/mcp-servers.md](../features/mcp-servers.md).
