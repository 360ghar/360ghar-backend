"""Typed payloads for the ChatGPT widgets.

Each widget name in ``app.mcp.chatgpt.WIDGETS`` has exactly one payload model and
one producer. The producer validates a tool result into the model. The same
payload is the MCP ``structuredContent`` and the agent ``widget`` frame body, so
both surfaces send one shape.

The models declare the keys each widget reads. Other keys the tool sends pass
through unchanged (``extra="allow"``), so a tool can add data without a model change.
Error results keep their ``error`` and ``message`` keys.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.logging import get_logger

logger = get_logger(__name__)

Number = int | float


class WidgetPayload(BaseModel):
    """Base for every widget payload. Undeclared keys pass through."""

    model_config = ConfigDict(extra="allow")

    error: bool | None = None
    message: str | None = None


class _PagedPayload(WidgetPayload):
    """Cursor page keys shared by the list widgets."""

    items: list[dict[str, Any]] | None = None
    total: int | None = None
    limit: int | None = None
    has_more: bool | None = None
    next_cursor: str | None = None


class PropertySearchPayload(_PagedPayload):
    """PropertySearchWidget: discovery_search and discovery_recommendations."""


class PropertyDetailsPayload(WidgetPayload):
    """PropertyDetailsWidget: one property, with the active lease when the caller has one."""

    property: dict[str, Any] | None = None
    active_lease: dict[str, Any] | None = None


class PropertySwipePayload(_PagedPayload):
    """PropertySwipeWidget: discovery_feed cards."""


class VisitSchedulerPayload(WidgetPayload):
    """VisitSchedulerWidget: the visit or booking just scheduled, and its property."""

    visit: dict[str, Any] | None = None
    booking: dict[str, Any] | None = None
    property: dict[str, Any] | None = None


class VisitListPayload(_PagedPayload):
    """VisitListWidget: visits or bookings, with per-status counts."""

    counts: dict[str, Any] | None = None


class LeaseDetailsPayload(WidgetPayload):
    """LeaseDetailsWidget: the tenant's current lease."""

    lease: dict[str, Any] | None = None


class MaintenancePayload(_PagedPayload):
    """MaintenanceWidget: maintenance requests, or one request after a create."""

    request: dict[str, Any] | None = None


class OwnerDashboardPayload(_PagedPayload):
    """OwnerDashboardWidget: property rows with the portfolio stats."""

    stats: dict[str, Any] | None = None


class LeaseManagementPayload(_PagedPayload):
    """LeaseManagementWidget: one lease, or the leases of the owner or agent scope with stats."""

    leases: list[dict[str, Any]] | None = None
    stats: dict[str, Any] | None = None
    lease: dict[str, Any] | None = None


class RentTotals(BaseModel):
    """The totals object of every rent collection result. Each total covers the full matching set."""

    model_config = ConfigDict(extra="allow")

    total_due: Number | None = None
    total_paid: Number | None = None
    overdue_count: int | None = None
    charges_count: int | None = None


class RentCollectionPayload(_PagedPayload):
    """RentCollectionWidget: rent charges or payments, with one totals object."""

    charges: list[dict[str, Any]] | None = None
    totals: RentTotals | None = None
    payment: dict[str, Any] | None = None


class TenantRentPayload(_PagedPayload):
    """TenantRentWidget: the tenant's rent dues and payment history."""

    total_collected: Number | None = None


def produce_property_search(data: Mapping[str, Any]) -> PropertySearchPayload:
    return PropertySearchPayload.model_validate(dict(data))


def produce_property_details(data: Mapping[str, Any]) -> PropertyDetailsPayload:
    return PropertyDetailsPayload.model_validate(dict(data))


def produce_property_swipe(data: Mapping[str, Any]) -> PropertySwipePayload:
    return PropertySwipePayload.model_validate(dict(data))


def produce_visit_scheduler(data: Mapping[str, Any]) -> VisitSchedulerPayload:
    return VisitSchedulerPayload.model_validate(dict(data))


def produce_visit_list(data: Mapping[str, Any]) -> VisitListPayload:
    return VisitListPayload.model_validate(dict(data))


def produce_lease_details(data: Mapping[str, Any]) -> LeaseDetailsPayload:
    return LeaseDetailsPayload.model_validate(dict(data))


def produce_maintenance(data: Mapping[str, Any]) -> MaintenancePayload:
    return MaintenancePayload.model_validate(dict(data))


def produce_owner_dashboard(data: Mapping[str, Any]) -> OwnerDashboardPayload:
    return OwnerDashboardPayload.model_validate(dict(data))


def produce_lease_management(data: Mapping[str, Any]) -> LeaseManagementPayload:
    return LeaseManagementPayload.model_validate(dict(data))


def produce_rent_collection(data: Mapping[str, Any]) -> RentCollectionPayload:
    return RentCollectionPayload.model_validate(dict(data))


def produce_tenant_rent(data: Mapping[str, Any]) -> TenantRentPayload:
    return TenantRentPayload.model_validate(dict(data))


class WidgetBinding(NamedTuple):
    """The one payload model and the one producer for a widget name."""

    model: type[WidgetPayload]
    produce: Callable[[Mapping[str, Any]], WidgetPayload]


WIDGET_PAYLOADS: dict[str, WidgetBinding] = {
    "PropertySearchWidget": WidgetBinding(PropertySearchPayload, produce_property_search),
    "PropertyDetailsWidget": WidgetBinding(PropertyDetailsPayload, produce_property_details),
    "PropertySwipeWidget": WidgetBinding(PropertySwipePayload, produce_property_swipe),
    "VisitSchedulerWidget": WidgetBinding(VisitSchedulerPayload, produce_visit_scheduler),
    "VisitListWidget": WidgetBinding(VisitListPayload, produce_visit_list),
    "LeaseDetailsWidget": WidgetBinding(LeaseDetailsPayload, produce_lease_details),
    "MaintenanceWidget": WidgetBinding(MaintenancePayload, produce_maintenance),
    "OwnerDashboardWidget": WidgetBinding(OwnerDashboardPayload, produce_owner_dashboard),
    "LeaseManagementWidget": WidgetBinding(LeaseManagementPayload, produce_lease_management),
    "RentCollectionWidget": WidgetBinding(RentCollectionPayload, produce_rent_collection),
    "TenantRentWidget": WidgetBinding(TenantRentPayload, produce_tenant_rent),
}


def widget_payload(widget_name: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """The JSON payload for a widget. A result the model cannot hold is sent unchanged."""
    binding = WIDGET_PAYLOADS.get(widget_name)
    if binding is None:
        return dict(data)
    try:
        payload = binding.produce(data)
    except ValidationError:
        logger.warning("Widget payload for %s did not match its model; sent unchanged", widget_name)
        return dict(data)
    return payload.model_dump(mode="json", exclude_unset=True)
