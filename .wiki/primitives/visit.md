# Visit

Visits are scheduled property walk-throughs. They span two contexts: a `property_tour` (a seeker touring a listing with an agent) and a `flatmate_meet` (two matched flatmates meeting at a listing). The Visit model unifies both flows behind a single table, with optional foreign keys that disambiguate the context.

Active contributors: Saksham, Ravi

## Model

File: `app/models/properties.py` (the `Visit` class, near the bottom of the file)

Key columns:

- `user_id` - the visitor. `ON DELETE CASCADE` from `users`.
- `property_id` - the listing being visited. `ON DELETE CASCADE` from `properties`.
- `agent_id` - nullable. Assigned by the load-balancing flow described in [agent.md](agent.md). `ON DELETE` defaults to restrict.
- `counterparty_user_id` - nullable. Set only for `flatmate_meet` visits, pointing to the other matched user. `ON DELETE SET NULL`.
- `conversation_id` - nullable. Links the visit back to the `UserConversation` it was scheduled from, for flatmate meetings. `ON DELETE SET NULL`.
- `match_id` - nullable. Links to the `UserMatch` record for flatmate meetings.
- `visit_context` - string defaulting to `property_tour`. Matches the `VisitContext` enum (`property_tour`, `flatmate_meet`) but stored as a string for forward compatibility.
- `scheduled_date`, `actual_date` - planned and actual visit times
- `status` - `VisitStatus` enum (`scheduled`, `confirmed`, `completed`, `cancelled`, `rescheduled`)
- `special_requirements`, `visit_notes`, `visitor_feedback`, `interest_level` - freeform and structured feedback
- `follow_up_required`, `follow_up_date` - agent follow-up tracking
- `cancellation_reason`, `rescheduled_from` - audit fields for state transitions

## Service layer

File: `app/services/visit.py` (547 lines)

The visit service handles both contexts through a single create path. For `flatmate_meet` visits, `_validate_flatmate_visit_context` enforces that a `counterparty_user_id` is present and that the pair has an active match. The canonical pair helper `_canonical_pair(user_id, other_user_id)` sorts the two IDs so lookups are order-independent.

Visits load with eager-selectinload options for property images, amenities, counterparty user, and agent, so the API response is single-query.

## Agent assignment

For `property_tour` visits, the service picks an agent using the load-balancing rules in [agent.md](agent.md). If no agent is available, the visit is created with `agent_id = NULL` and `status = scheduled`, and an agent is assigned later through the `/api/v1/visits/{id}/assign` flow or the admin MCP `agent_*` tools.

## REST and MCP surfaces

The `/api/v1/visits` router covers schedule, list, get, cancel, and reschedule. The user MCP server exposes `visits_schedule`, `visits_list`, `visits_get`, and `visits_cancel`. Visit scheduling also fires an SSE `visit_updated` event for real-time UI updates.
