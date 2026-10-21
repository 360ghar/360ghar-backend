"""The default migration runner applies every *.sql file in supabase/migrations.

A file marked DO NOT APPLY must not sit there. The runner has no guard for the
marker, so the marker only works if the file is kept out of the folder.
"""

from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
_MARKER_RE = re.compile(r"do\s+not\s+apply", re.IGNORECASE)


def test_no_migration_file_is_marked_do_not_apply() -> None:
    marked = [
        path.name
        for path in sorted(MIGRATIONS_DIR.glob("*.sql"))
        if _MARKER_RE.search(path.read_text(encoding="utf-8"))
    ]
    assert not marked, f"move these out of supabase/migrations (DO NOT APPLY): {marked}"


_CHAT_RLS_FILE = "20261014007003_messages_rls_deny_direct_reads.sql"


def test_chat_table_rls_migration_is_applied_by_the_runner() -> None:
    """Both flatmates chat clients read messages through broadcast only, so RLS on
    public.messages (no policy) is a normal migration. supabase/held/ is gone."""
    path = MIGRATIONS_DIR / _CHAT_RLS_FILE
    assert path.is_file()
    assert re.search(
        r"alter\s+table\s+public\.messages\s+enable\s+row\s+level\s+security",
        path.read_text(encoding="utf-8"),
        re.IGNORECASE,
    )
    assert not (MIGRATIONS_DIR.parent / "held").exists()
