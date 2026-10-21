"""The import scripts: URL parsing and snapshot rows. No database."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))

import import_localities  # noqa: E402


@pytest.mark.parametrize(
    ("raw", "host", "password"),
    [
        ("postgresql://u:p%40ss@localhost:5432/db", "localhost", "p@ss"),
        ("postgresql://u:p@ss@localhost:5432/db", "localhost", "p@ss"),
        ("postgres://u:pw@[::1]:5432/db", "::1", "pw"),
        ("postgresql://u@localhost/db", "localhost", None),
    ],
)
def test_parse_url_keeps_host_and_password(raw, host, password):
    url = import_localities.parse_url(raw)
    assert url.host == host and url.password == password


def test_snapshot_rows_cover_every_place_with_landmarks_as_json():
    rows = import_localities.snapshot_rows()
    assert len(rows) > 1000 and all(r["slug"] and r["city"] for r in rows)
    with_landmarks = [r for r in rows if r["landmarks"] != "[]"]
    assert with_landmarks and {r["place_type"] for r in rows} <= {
        "locality", "sector", "society", "village", "road", "township", "phase",
    }
