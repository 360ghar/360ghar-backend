# Maintainers

360Ghar is a small team. There is no `CODEOWNERS` file - review is coordinated informally between the two active contributors. This page maps subsystems to the contributor who owns them, so external contributors know who to ping.

Active contributors: Saksham, Ravi

## Contributors

| Contributor | Commits | Role |
|---|---|---|
| Saksham Mittal | 165 | Primary maintainer. Owns all subsystems. |
| Ravi Sahu | 16 | Trusted contributor across feature work. |
| railway-app[bot] | 1 | Deploy bot. |

## Subsystem ownership

Saksham owns every subsystem - core API, auth, middleware, Ghar Core, 360 Stays, Flatmates, Property Management, 360 Virtual Tours, 360 Data Hub, MCP servers and widgets, AI agent and providers, blog, notifications, infrastructure, vector search, storage, tests/CI, and deployment. He authored the vast majority of the codebase (165 of 182 commits). Ravi's 16 commits are spread across feature work; he is a trusted contributor but not the primary owner of any single area. When in doubt, ping Saksham.

## Review process

Pull requests target `main`. CI runs on every PR: docs-contracts validation (against `docs/repo-contract.json`), pytest with `--cov-fail-under=90`, `ruff check app/`, and `mypy app/`. New endpoints, services, MCP tools, or schedulers must be registered in the contract or CI fails. There is no formal review SLA - the team is small and async.

See [how-to-contribute/](../how-to-contribute/) for the development workflow. The short version: fork, branch, run `uv sync --extra dev`, run `uv run pytest tests/ -v` and `uv run ruff check app/` before pushing, open a PR against `main`.
