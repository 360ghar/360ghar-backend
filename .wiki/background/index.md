# Background and design decisions

This section captures the historical context and architectural decisions that shaped the 360Ghar backend. The four ADRs in `docs/adrs/` document decisions that have been accepted but not yet fully implemented - they describe where the codebase is heading, not always where it is today. The pitfalls page documents non-obvious business rules and trade-offs that have bitten contributors before.

Active contributors: Saksham, Ravi

## Pages

- [design-decisions.md](design-decisions.md) - Summaries of the four ADRs
- [pitfalls.md](pitfalls.md) - Non-obvious rules and trade-offs (overlapping bookings, serverless mode, ephemeral httpx, double-booking guards)

## ADR index

| ADR | Title | Status |
|---|---|---|
| 001 | Domain-Driven Module Structure | Accepted |
| 002 | Repository Pattern with Protocol Interfaces | Accepted |
| 003 | Event-Driven Side Effects | Accepted |
| 004 | Adapter Pattern for External Services | Accepted |

All four were written on 2026-05-08. They describe a target architecture that the codebase is migrating toward. The current layout in `app/api/`, `app/services/`, `app/models/`, `app/repositories/` is the type-based (layered) layout that ADR 001 proposes moving away from.

## Why these matter

The ADRs exist because the codebase hit real pain points: scattered MCP tool logic, services bypassing repositories, blocking side effects in the request path, and inconsistent retry behavior across external services. Each ADR documents the problem, the decision, and the migration path. Reading them before a major refactor prevents re-litigating decisions that were already made.
