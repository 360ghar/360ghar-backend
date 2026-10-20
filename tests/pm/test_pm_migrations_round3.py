"""Run the PM migrations against a pre-migration state, inside the test transaction.

The test schema is built from the models, which already carry the target state. Each test
puts the columns back to the state the migration starts from, runs the migration file, and
reads the result. The transaction is rolled back after each test.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.enums import (
    ExpenseCategory,
    LeaseStatus,
    MaintenanceCategory,
    MaintenanceRequestStatus,
    MaintenanceUrgency,
)
from app.models.pm_finance import Expense
from app.models.pm_leases import Lease
from app.models.pm_maintenance import MaintenanceRequest
from app.models.pm_tenants import RentalApplication, RentalApplicationForm
from tests.pm.test_pm_contract_wave3 import _document, _lease, _property, _user

pytestmark = pytest.mark.asyncio

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


async def _run(db_session, name: str) -> None:
    """Run a whole migration file on the session's connection.

    The driver formats '%' even with no parameters, so each '%' is doubled. This keeps the
    RAISE message text intact.
    """
    conn = await db_session.connection()
    await conn.exec_driver_sql((MIGRATIONS / name).read_text().replace("%", "%%"))


async def _scalar(db_session, sql: str):
    conn = await db_session.connection()
    return (await conn.exec_driver_sql(sql)).scalar_one()


async def _nullable(db_session, table: str, column: str) -> str:
    return await _scalar(
        db_session,
        "SELECT is_nullable FROM information_schema.columns "
        f"WHERE table_name = '{table}' AND column_name = '{column}'",
    )


# ---------------------------------------------------------------------------
# 20261014005022: money exact and the document share flags NOT NULL (be-pm-24, be-pm-14).
# ---------------------------------------------------------------------------


async def test_005022_backfills_share_flags_and_makes_the_fee_exact(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, None)
    doc = await _document(db_session, owner)
    form = RentalApplicationForm(
        owner_id=owner.id,
        property_id=prop.id,
        title="F",
        slug="fee-form",
        application_fee_amount=1234.56,
    )
    db_session.add(form)
    await db_session.flush()

    # Pre-migration state: nullable flags, REAL money and percentage.
    conn = await db_session.connection()
    await conn.exec_driver_sql(
        "ALTER TABLE documents "
        "ALTER COLUMN shared_with_tenant DROP NOT NULL, ALTER COLUMN shared_with_tenant DROP DEFAULT, "
        "ALTER COLUMN shared_with_agent DROP NOT NULL, ALTER COLUMN shared_with_agent DROP DEFAULT"
    )
    await conn.exec_driver_sql(
        "ALTER TABLE rental_application_forms ALTER COLUMN application_fee_amount TYPE REAL"
    )
    await conn.exec_driver_sql("ALTER TABLE leases ALTER COLUMN late_fee_percentage TYPE REAL")
    await conn.exec_driver_sql(
        f"UPDATE documents SET shared_with_tenant = NULL, shared_with_agent = NULL WHERE id = {doc.id}"
    )
    await conn.exec_driver_sql(f"UPDATE leases SET late_fee_percentage = 7.3 WHERE id = {lease.id}")

    await _run(db_session, "20261014005022_pm_drift_fee_and_share_flags.sql")

    flags = (
        await conn.exec_driver_sql(
            f"SELECT shared_with_tenant, shared_with_agent FROM documents WHERE id = {doc.id}"
        )
    ).one()
    assert tuple(flags) == (False, False)
    assert await _nullable(db_session, "documents", "shared_with_tenant") == "NO"
    assert await _nullable(db_session, "documents", "shared_with_agent") == "NO"
    assert await _scalar(
        db_session,
        f"SELECT application_fee_amount FROM rental_application_forms WHERE id = {form.id}",
    ) == Decimal("1234.56")
    assert (
        await _scalar(db_session, f"SELECT late_fee_percentage FROM leases WHERE id = {lease.id}")
        == 7.3
    )


# ---------------------------------------------------------------------------
# 20261014005011: drops only the columns that hold no user data (lead decision).
# ---------------------------------------------------------------------------


async def _has_column(db_session, table: str, column: str) -> bool:
    return bool(
        await _scalar(
            db_session,
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            f"WHERE table_name = '{table}' AND column_name = '{column}')",
        )
    )


async def test_005011_keeps_the_columns_that_can_hold_user_data(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    doc = await _document(db_session, owner)
    request = MaintenanceRequest(
        property_id=prop.id,
        owner_id=owner.id,
        category=MaintenanceCategory.plumbing,
        urgency=MaintenanceUrgency.medium,
        title="Leak",
        request_status=MaintenanceRequestStatus.open,
    )
    expense = Expense(
        property_id=prop.id,
        owner_id=owner.id,
        category=ExpenseCategory.repairs,
        amount=Decimal("100.00"),
        expense_date=date(2026, 10, 1),
    )
    db_session.add_all([request, expense])
    await db_session.flush()

    # Pre-migration state: the legacy columns exist and hold values a user entered.
    conn = await db_session.connection()
    for statement in (
        "ALTER TABLE maintenance_requests ADD COLUMN priority TEXT",
        "ALTER TABLE expenses ADD COLUMN is_recurring BOOLEAN DEFAULT FALSE, "
        "ADD COLUMN recurrence_rule JSONB, ADD COLUMN next_due_date DATE",
        "ALTER TABLE documents ADD COLUMN version INTEGER DEFAULT 1, "
        "ADD COLUMN replaces_document_id BIGINT",
        f"UPDATE maintenance_requests SET priority = 'urgent' WHERE id = {request.id}",
        "UPDATE expenses SET is_recurring = TRUE, "
        "recurrence_rule = '{\"every\": \"month\"}', next_due_date = '2026-11-01' "
        f"WHERE id = {expense.id}",
    ):
        await conn.exec_driver_sql(statement)

    await _run(db_session, "20261014005011_pm_drop_dead_fields.sql")

    # Kept: the values a user typed are still there.
    assert await _scalar(
        db_session, f"SELECT priority FROM maintenance_requests WHERE id = {request.id}"
    ) == "urgent"
    row = (
        await conn.exec_driver_sql(
            "SELECT is_recurring, recurrence_rule, next_due_date "
            f"FROM expenses WHERE id = {expense.id}"
        )
    ).one()
    assert row[0] is True
    assert row[1] == {"every": "month"}
    assert row[2] == date(2026, 11, 1)
    # Dropped: no user data.
    assert not await _has_column(db_session, "documents", "version")
    assert not await _has_column(db_session, "documents", "replaces_document_id")
    assert await _scalar(db_session, f"SELECT count(*) FROM documents WHERE id = {doc.id}") == 1


# ---------------------------------------------------------------------------
# 20261014005020: one occupying lease per property, expiring_soon included (be-pm-10).
# ---------------------------------------------------------------------------


async def test_005020_stops_on_two_occupying_leases_for_one_property(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    await _lease(db_session, owner, prop, None)  # active

    # Rows as they were before the index: drop it, then add the second occupying lease.
    conn = await db_session.connection()
    await conn.exec_driver_sql("DROP INDEX uq_leases_property_active")
    db_session.add(
        Lease(
            property_id=prop.id,
            owner_id=owner.id,
            status=LeaseStatus.expiring_soon,
            start_date=date(2026, 1, 1),
            end_date=date(2027, 12, 31),
            monthly_rent=Decimal("20000.00"),
            security_deposit=Decimal("0.00"),
            grace_period_days=5,
            payment_due_day=5,
        )
    )
    await db_session.flush()

    # The error rolls the savepoint back, so the rest of the test transaction stays usable.
    with pytest.raises(DBAPIError, match="more than one active or expiring_soon lease"):
        async with db_session.begin_nested():
            await _run(db_session, "20261014005020_pm_lease_occupancy_index.sql")


async def test_005020_creates_the_index_that_the_models_declare(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    await _lease(db_session, owner, prop, None)  # active only

    conn = await db_session.connection()
    await conn.exec_driver_sql("DROP INDEX uq_leases_property_active")
    await _run(db_session, "20261014005020_pm_lease_occupancy_index.sql")

    definition = await _scalar(
        db_session,
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_leases_property_active'",
    )
    assert "UNIQUE" in definition
    assert "expiring_soon" in definition

    # The index now refuses a second occupying lease, whichever occupying status it has.
    db_session.add(
        Lease(
            property_id=prop.id,
            owner_id=owner.id,
            status=LeaseStatus.expiring_soon,
            start_date=date(2026, 1, 1),
            end_date=date(2027, 12, 31),
            monthly_rent=Decimal("20000.00"),
            security_deposit=Decimal("0.00"),
            grace_period_days=5,
            payment_due_day=5,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ---------------------------------------------------------------------------
# 20261014005021: NOT NULL with backfill on the columns the models declare NOT NULL
# (be-pm-42, be-pm-43, be-pm-44, be-pm-45).
# ---------------------------------------------------------------------------


async def test_005021_backfills_and_sets_not_null_on_the_declared_columns(db_session):
    owner = await _user(db_session, name="Owner")
    prop = await _property(db_session, owner)
    lease = await _lease(db_session, owner, prop, None)
    form = RentalApplicationForm(
        owner_id=owner.id, property_id=prop.id, title="F", slug="nullable-form"
    )
    db_session.add(form)
    await db_session.flush()
    application = RentalApplication(
        form_id=form.id,
        property_id=prop.id,
        owner_id=owner.id,
        applicant_full_name="Null Status",
        submitted_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    db_session.add(application)
    await db_session.flush()

    conn = await db_session.connection()
    await conn.exec_driver_sql(
        "ALTER TABLE leases ALTER COLUMN grace_period_days DROP NOT NULL, "
        "ALTER COLUMN payment_due_day DROP NOT NULL"
    )
    await conn.exec_driver_sql(
        "ALTER TABLE rent_charges ALTER COLUMN late_fee_assessed DROP NOT NULL"
    )
    await conn.exec_driver_sql("ALTER TABLE rental_applications ALTER COLUMN status DROP NOT NULL")
    await conn.exec_driver_sql(
        "ALTER TABLE rental_application_forms ALTER COLUMN is_active DROP NOT NULL"
    )
    await conn.exec_driver_sql(
        f"UPDATE leases SET grace_period_days = NULL, payment_due_day = NULL WHERE id = {lease.id}"
    )
    await conn.exec_driver_sql(
        f"UPDATE rental_applications SET status = NULL WHERE id = {application.id}"
    )
    await conn.exec_driver_sql(
        f"UPDATE rental_application_forms SET is_active = NULL WHERE id = {form.id}"
    )

    await _run(db_session, "20261014005021_pm_not_null_backfill.sql")

    # The backfill copies the managed property's values (the lease had none stored).
    grace, due_day = (
        await conn.exec_driver_sql(
            f"SELECT grace_period_days, payment_due_day FROM properties WHERE id = {prop.id}"
        )
    ).one()
    assert (
        await _scalar(db_session, f"SELECT grace_period_days FROM leases WHERE id = {lease.id}")
        == grace
    )
    assert (
        await _scalar(db_session, f"SELECT payment_due_day FROM leases WHERE id = {lease.id}")
        == due_day
    )
    assert (
        await _scalar(
            db_session, f"SELECT status FROM rental_applications WHERE id = {application.id}"
        )
    ) == "applicant"
    assert (
        await _scalar(
            db_session, f"SELECT is_active FROM rental_application_forms WHERE id = {form.id}"
        )
    ) is True
    assert await _nullable(db_session, "leases", "grace_period_days") == "NO"
    assert await _nullable(db_session, "rental_applications", "status") == "NO"
    assert await _nullable(db_session, "rental_application_forms", "is_active") == "NO"
