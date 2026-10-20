"""Seed JSON must fit the ORM and the migrated schema (contract-audit S1, S3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.core import AppVersion
from app.models.data_hub import AuctionAlert
from app.models.enums import AppKey, RentalApplicationStatus
from app.models.users import User

SEED = Path(__file__).resolve().parents[2] / "seed_data"


def _load(rel: str) -> list[dict]:
    return json.loads((SEED / rel).read_text(encoding="utf-8"))


def _unknown_keys(records: list[dict], model) -> set[str]:
    cols = set(model.__table__.columns.keys())
    keys = {k for r in records for k in r if not k.startswith("_")}
    return {k for k in keys if k not in cols and not k.endswith("_ref")}


@pytest.mark.parametrize("rel", ["seed/01_users.json", "hardcoded/01_users.json"])
def test_user_records_use_only_orm_columns(rel):
    assert _unknown_keys(_load(rel), User) == set()


def test_auction_alert_records_use_only_orm_columns():
    assert _unknown_keys(_load("generated/15_auction_alerts.json"), AuctionAlert) == set()


def test_app_versions_use_allowed_app_keys():
    assert {r["app"] for r in _load("hardcoded/07_app_versions.json")} <= {k.value for k in AppKey}
    assert _unknown_keys(_load("hardcoded/07_app_versions.json"), AppVersion) == set()


def test_rental_application_statuses_are_valid():
    allowed = {s.value for s in RentalApplicationStatus}
    statuses = {
        r["status"] for r in _load("seed/16_rental_applications.json") if r.get("_type") == "application"
    }
    assert statuses <= allowed
