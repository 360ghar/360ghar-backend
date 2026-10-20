from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    MaintenanceCategory,
    MaintenanceRequestStatus,
    MaintenanceUrgency,
    WorkOrderStatus,
)
from app.schemas.base import Money, NotNullable, PatchModel, UtcDateTime, WriteModel


class MaintenanceRequestCreate(WriteModel):
    property_id: int
    lease_id: int | None = Field(default=None, description="Lease for this property, if any")
    category: MaintenanceCategory
    urgency: MaintenanceUrgency
    title: str
    description: str | None = None
    preferred_contact_method: str | None = None
    availability_notes: str | None = None
    estimated_cost: Annotated[Money | None, Field(ge=0)] = None
    scheduled_for: UtcDateTime | None = None
    assigned_agent_id: int | None = None


class MaintenanceRequestUpdate(PatchModel):
    request_status: Annotated[MaintenanceRequestStatus | None, NotNullable] = None
    urgency: Annotated[MaintenanceUrgency | None, NotNullable] = None
    assigned_agent_id: int | None = None
    work_order_status: WorkOrderStatus | None = None
    estimated_cost: Annotated[Money | None, Field(ge=0)] = None
    actual_cost: Annotated[Money | None, Field(ge=0)] = None
    scheduled_for: UtcDateTime | None = None
    completed_at: UtcDateTime | None = None
    closed_at: UtcDateTime | None = None
    completion_notes: str | None = None
    vendor_name: str | None = None
    vendor_contact: str | None = None


class MaintenanceRequest(BaseModel):
    id: int
    property_id: int
    property_title: str | None = None
    lease_id: int | None = None
    owner_id: int
    tenant_user_id: int | None = None
    tenant_name: str | None = None
    category: MaintenanceCategory
    urgency: MaintenanceUrgency
    title: str
    description: str | None = None
    preferred_contact_method: str | None = None
    availability_notes: str | None = None
    request_status: MaintenanceRequestStatus
    assigned_agent_id: int | None = None
    work_order_status: WorkOrderStatus | None = None
    estimated_cost: Money | None = None
    actual_cost: Money | None = None
    scheduled_for: UtcDateTime | None = None
    completed_at: UtcDateTime | None = None
    closed_at: UtcDateTime | None = None
    completion_notes: str | None = None
    vendor_name: str | None = None
    vendor_contact: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True)
