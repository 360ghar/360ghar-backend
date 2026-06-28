"""
E2E test for the PM (Property Management) lifecycle flow.

Tests the complete flow: property -> lease -> rent charges -> maintenance -> termination.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import (
    LeaseStatus,
    MaintenanceCategory,
    MaintenanceRequestStatus,
    MaintenanceUrgency,
    RentChargeStatus,
)
from tests.fixtures.factories import PropertyFactory, UserFactory


class TestPMLifecycleFlow:
    """End-to-end test for PM lifecycle."""

    @pytest.mark.asyncio
    async def test_lease_to_rent_to_maintenance_flow(
        self,
        db_session: AsyncSession,
        test_user,
    ):
        """Full PM lifecycle: create property -> create lease -> rent -> maintenance."""
        # Step 1: Create a managed property
        property_obj = await PropertyFactory.create(
            db_session,
            owner=test_user,
            title="PM Lifecycle Property",
            property_type="apartment",
            purpose="rent",
            monthly_rent=Decimal("30000"),
            is_managed=True,
        )
        assert property_obj.is_managed is True

        # Step 2: Create a tenant
        tenant = await UserFactory.create(
            db_session,
            email="pm_tenant@example.com",
            phone="+919111222333",
            full_name="PM Tenant",
        )

        # Step 3: Create a lease
        from app.models.pm_leases import Lease

        lease = Lease(
            property_id=property_obj.id,
            owner_id=test_user.id,
            tenant_user_id=tenant.id,
            tenant_name=tenant.full_name,
            tenant_phone=tenant.phone,
            tenant_email=tenant.email,
            status=LeaseStatus.active,
            start_date=date.today() - timedelta(days=30),
            end_date=date.today() + timedelta(days=335),
            monthly_rent=30000.0,
            security_deposit=60000.0,
            late_fee_amount=500.0,
            grace_period_days=5,
            payment_due_day=1,
        )
        db_session.add(lease)
        await db_session.flush()
        await db_session.refresh(lease)
        assert lease.id is not None
        assert lease.status == LeaseStatus.active

        # Step 4: Create a rent charge
        from app.models.pm_finance import RentCharge

        today = date.today()
        billing_month = today.replace(day=1)
        rent_charge = RentCharge(
            lease_id=lease.id,
            property_id=property_obj.id,
            owner_id=test_user.id,
            tenant_user_id=tenant.id,
            billing_month=billing_month,
            period_start=billing_month,
            period_end=(billing_month + timedelta(days=32)).replace(day=1) - timedelta(days=1),
            due_date=billing_month.replace(day=5),
            amount_due=30000.0,
            status=RentChargeStatus.pending,
        )
        db_session.add(rent_charge)
        await db_session.flush()
        await db_session.refresh(rent_charge)
        assert rent_charge.status == RentChargeStatus.pending

        # Step 5: Create a maintenance request
        from app.models.pm_maintenance import MaintenanceRequest

        maint_request = MaintenanceRequest(
            property_id=property_obj.id,
            lease_id=lease.id,
            owner_id=test_user.id,
            tenant_user_id=tenant.id,
            category=MaintenanceCategory.plumbing,
            urgency=MaintenanceUrgency.medium,
            title="Leaky faucet",
            description="Kitchen faucet is dripping",
            request_status=MaintenanceRequestStatus.open,
        )
        db_session.add(maint_request)
        await db_session.flush()
        await db_session.refresh(maint_request)
        assert maint_request.request_status == MaintenanceRequestStatus.open

        # Step 6: Terminate the lease
        lease.status = LeaseStatus.terminated
        await db_session.flush()
        await db_session.refresh(lease)
        assert lease.status == LeaseStatus.terminated
