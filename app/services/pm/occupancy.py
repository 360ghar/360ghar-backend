"""Shared "occupied" definition: one lease status set for lists, reports and dashboards."""

from __future__ import annotations

from sqlalchemy import and_, exists, select

from app.models.enums import LeaseStatus
from app.models.pm_leases import Lease
from app.models.properties import Property

# A tenant still occupies the unit while the lease is active or in its notice window.
OCCUPIED_LEASE_STATUSES = (LeaseStatus.active, LeaseStatus.expiring_soon)


def active_lease_exists():  # noqa: ANN201 - SQLAlchemy Exists expression
    """Correlated EXISTS: the property has an occupying lease."""
    return exists(
        select(1).where(
            and_(
                Lease.property_id == Property.id,
                Lease.status.in_(OCCUPIED_LEASE_STATUSES),
            )
        )
    )
