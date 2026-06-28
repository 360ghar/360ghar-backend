# Cleanup opportunities

This section documents known cleanup opportunities in the 360Ghar backend. The codebase is notably clean for its size - only two `TODO`/`FIXME` comments exist across all of `app/` - so this section is thin by design. The complexity hotspots page calls out the largest files that may benefit from decomposition.

Active contributors: Saksham, Ravi

## Pages

- [complexity-hotspots.md](complexity-hotspots.md) - The largest source files and what they do
- [todos-and-fixmes.md](todos-and-fixmes.md) - The two TODO comments and their context

## Overall state

- 67,841 lines of code in `app/`, 33,125 lines in `tests/` (49% test-to-code ratio)
- 352 Python source files, 159 test files
- Only 2 `TODO`/`FIXME` comments in `app/` - well below average for a codebase this size
- 4 accepted ADRs that describe target architecture not yet implemented (see [background/design-decisions.md](../background/design-decisions.md))

The biggest cleanup lever is not chasing TODOs but executing the ADR migration: moving toward domain-driven modules (ADR 001), protocol-based repositories (ADR 002), an event bus for side effects (ADR 003), and adapter interfaces for external services (ADR 004). Each ADR is a multi-quarter effort, not a weekend refactor.
