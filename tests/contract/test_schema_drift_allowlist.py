"""The schema drift allowlist keeps only differences that have a stated reason.

Wave 3d cut the list from 94 lines to the ones that cannot be fixed in the models or a
migration. A new line needs a one-line reason, and the type and nullability groups stay closed.
"""

from __future__ import annotations

from pathlib import Path

from scripts.verify_schema_drift import DEFAULT_ALLOWLIST, load_allowlist


def _lines(path: Path) -> list[str]:
    return path.read_text().splitlines()


def test_every_allowlist_entry_has_a_reason_comment_directly_above() -> None:
    lines = _lines(DEFAULT_ALLOWLIST)
    entries = set(load_allowlist(DEFAULT_ALLOWLIST))
    for index, line in enumerate(lines):
        if line.strip() in entries:
            above = lines[index - 1].strip() if index else ""
            assert above.startswith("#") and len(above.lstrip("# ")) > 10, (
                f"allowlist line has no reason comment above it: {line}"
            )


def test_type_and_nullability_drift_cannot_return_to_the_allowlist() -> None:
    reopened = [
        entry
        for entry in load_allowlist(DEFAULT_ALLOWLIST)
        if entry.split(": ")[1] in {"type", "nullable"}
    ]
    assert not reopened, f"fix these in the models or a migration instead: {reopened}"
