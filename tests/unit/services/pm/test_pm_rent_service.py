"""
Tests for PM rent service module.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RentChargeStatus


class TestGenerateRentCharges:
    """Tests for generate_rent_charges function."""

    @pytest.mark.asyncio
    async def test_generate_monthly_charges(
        self,
        db_session: AsyncSession,
        test_user,
        test_active_lease,
    ):
        """Test generating monthly rent charges."""
        from app.services.pm_rent import generate_rent_charges

        result = await generate_rent_charges(
            db_session,
            actor=test_user,
            lease_id=test_active_lease.id,
            start_month=date.today().replace(day=1),
            months=1,
        )

        assert result is not None
        assert "created" in result
        assert "skipped" in result


class TestRecordRentPayment:
    """Tests for record_rent_payment function."""

    @pytest.mark.asyncio
    async def test_record_payment_success(
        self,
        db_session: AsyncSession,
        test_user,
        test_rent_charge,
    ):
        """Test successful rent payment recording."""
        from app.services.pm_rent import record_rent_payment

        result = await record_rent_payment(
            db_session,
            actor=test_user,
            charge_id=test_rent_charge.id,
            amount_paid=50000.0,
            payment_method="bank_transfer",
            paid_at=datetime.now(timezone.utc),
        )

        assert result is not None
        assert result.amount_paid == 50000.0
        assert result.payment_method == "bank_transfer"


class TestListRentCharges:
    """Tests for list_rent_charges function."""

    @pytest.mark.asyncio
    async def test_list_rent_charges_for_owner(
        self,
        db_session: AsyncSession,
        test_user,
        test_rent_charge,
    ):
        """Test listing rent charges for owner."""
        from app.services.pm_rent import list_rent_charges

        result, next_payload, count_total = await list_rent_charges(
            db_session,
            actor=test_user,
            cursor_payload={},
        )

        assert isinstance(result, list)
        assert len(result) >= 1
        # Check returned dict structure
        if result:
            item = result[0]
            assert "charge" in item
            assert "amount_paid_total" in item
            assert "outstanding" in item


class TestListRentPayments:
    """Tests for list_rent_payments function."""

    @pytest.mark.asyncio
    async def test_list_payments_for_owner(
        self,
        db_session: AsyncSession,
        test_user,
        test_rent_charge,
    ):
        """Test listing rent payments for owner."""
        from app.services.pm_rent import list_rent_payments, record_rent_payment

        # First record a payment
        await record_rent_payment(
            db_session,
            actor=test_user,
            charge_id=test_rent_charge.id,
            amount_paid=25000.0,
            paid_at=datetime.now(timezone.utc),
        )

        result, next_payload, count_total = await list_rent_payments(
            db_session,
            actor=test_user,
            cursor_payload={},
        )

        assert isinstance(result, list)
        assert len(result) >= 1


class TestRentChargeStatus:
    """Tests for rent charge status transitions."""

    def test_charge_status_values(self):
        """Test charge status enum values."""
        assert RentChargeStatus.pending.value == "pending"
        assert RentChargeStatus.paid.value == "paid"
        assert RentChargeStatus.partial.value == "partial"
        assert RentChargeStatus.overdue.value == "overdue"

    @pytest.mark.asyncio
    async def test_partial_payment_updates_status(
        self,
        db_session: AsyncSession,
        test_user,
        test_rent_charge,
    ):
        """Test that partial payment updates charge status."""
        from app.services.pm_rent import record_rent_payment

        # Make a partial payment
        await record_rent_payment(
            db_session,
            actor=test_user,
            charge_id=test_rent_charge.id,
            amount_paid=25000.0,  # Half of 50000
            paid_at=datetime.now(timezone.utc),
        )

        # Refresh the charge
        await db_session.refresh(test_rent_charge)

        # Status should be partial (or paid if we're testing with due date in future)
        assert test_rent_charge.status in [RentChargeStatus.partial, RentChargeStatus.overdue]

    @pytest.mark.asyncio
    async def test_full_payment_updates_status(
        self,
        db_session: AsyncSession,
        test_user,
        test_rent_charge,
    ):
        """Test that full payment updates charge status to paid."""
        from app.services.pm_rent import record_rent_payment

        # Make a full payment
        await record_rent_payment(
            db_session,
            actor=test_user,
            charge_id=test_rent_charge.id,
            amount_paid=50000.0,
            paid_at=datetime.now(timezone.utc),
        )

        # Refresh the charge
        await db_session.refresh(test_rent_charge)

        assert test_rent_charge.status == RentChargeStatus.paid
