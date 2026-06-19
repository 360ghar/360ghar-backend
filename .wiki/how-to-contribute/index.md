# How to contribute

*Active contributors: Saksham Mittal, Ravi Sahu. PRs welcome from anyone.*

This is the entry point for working on the 360Ghar backend. It covers how work is picked up, the PR process, review expectations, and the definition of done. For the step-by-step mechanics of branching, testing, and seeding data, see [development-workflow.md](development-workflow.md). For test expectations, see [testing.md](testing.md). For lint and build tooling, see [tooling.md](tooling.md). For conventions and patterns, see [patterns-and-conventions.md](patterns-and-conventions.md).

## Picking up work

Work is tracked through GitHub issues and PRs against `main`. There is no formal project board; coordination is informal because the team is two people. A few principles:

- Match the layer to the change. HTTP behavior goes in `app/api/api_v1/endpoints/`, business rules in `app/services/`, persistence in `app/models/`, transport shapes in `app/schemas/`. The [contribution contract](../../docs/contribution-contract.md) is the authoritative placement guide.
- Reuse before you create. MCP servers and the AI agent both call shared logic in `app/mcp/tool_ops/` and `app/services/ai_agent/tool_bridge.py`. Do not duplicate service-layer behavior in a new surface.
- Read the [architecture contract](../../docs/architecture-contract.md) before touching cross-cutting infrastructure. Lifespan wiring, schedulers, and shared httpx clients have specific ownership rules.
- Check [lore.md](../lore.md) for the current active refactor. As of June 2026, cursor pagination is rolling out across list endpoints; new list endpoints should follow the 3-tuple `(items, next_cursor, has_more)` pattern.

## PR process

1. Branch from `main`. Keep branches short-lived.
2. Run the full local gate before pushing: `uv run pytest tests/ -v`, `uv run ruff check app/`, `uv run mypy app/ --ignore-missing-imports`. See [tooling.md](tooling.md) for what each enforces.
3. Open a PR against `main`. Describe the change and call out any data-safety implications.
4. CI runs jobs on every push and PR (see [`.github/workflows/tests.yml`](../../.github/workflows/tests.yml)):
   - **test** boots PostGIS and Redis services, then runs `pytest tests/ -v --cov=app --cov-fail-under=90`. Coverage under 90% fails the build.
   - **lint** runs `ruff check app/` and `mypy app/`.
5. Request review. With a two-person team, review is light but expected for anything touching auth, schedulers, migrations, or data deletion paths.

## Review expectations

Reviewers look for:

- Correct layer placement and no duplicated business logic.
- Async-first database access with structured exceptions from `app/core/exceptions.py`.
- Tests in the narrowest layer that proves the behavior (see [testing.md](testing.md)).
- Updates to `docs/repo-contract.json` for any new endpoint, service, or MCP module.
- No new `AsyncIOScheduler` instances and no ephemeral `async with httpx.AsyncClient()`; use the shared scheduler and shared clients.
- No bare `DELETE FROM` on tables that could hold real user data. See [development-workflow.md](development-workflow.md) for the data safety rules.

## Definition of done

A change is ready to merge when:

- All three CI jobs pass.
- Coverage stays at or above 90%.
- `docs/repo-contract.json` is updated if the public surface changed.
- The relevant contract doc (`architecture-contract.md`, `testing-contract.md`, `contribution-contract.md`, `terminology-and-ownership.md`) is updated for new patterns, schedulers, notification types, SSE events, or storage paths.
- Any new outbound HTTP call uses a shared client from `app/core/http.py`.
- Any new background job is wired through `app/infrastructure/lifespan.py` and registers on the shared scheduler.

## Where to go next

- [development-workflow.md](development-workflow.md) for the branch-code-test-merge cycle.
- [testing.md](testing.md) for the test suite and coverage rules.
- [debugging.md](debugging.md) for logs, common errors, and troubleshooting.
- [tooling.md](tooling.md) for uv, ruff, mypy, Docker, and Supabase CLI.
- [patterns-and-conventions.md](patterns-and-conventions.md) for the coding conventions enforced by ruff.
