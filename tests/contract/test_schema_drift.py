"""Full schema parity between app/models and a migrated database.

Skipped unless CONTRACT_DRIFT_DATABASE_URL points at a database where every
file in supabase/migrations has been applied (CI builds one). The check is
read-only. Known differences are listed in scripts/schema_drift_allowlist.txt.
"""

from __future__ import annotations

import os

import pytest

DRIFT_URL = os.environ.get("CONTRACT_DRIFT_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DRIFT_URL, reason="CONTRACT_DRIFT_DATABASE_URL is not set")


def test_models_match_migrated_schema() -> None:
    from scripts.verify_schema_drift import check_drift

    assert DRIFT_URL is not None
    problems = check_drift(database_url=DRIFT_URL)
    assert not problems, "schema drift:\n" + "\n".join(problems)
