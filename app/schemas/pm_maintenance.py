from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    MaintenanceCategory,
    MaintenanceRequestStatus,
    MaintenanceUrgency,
    WorkOrderStatus,
)


class MaintenanceRequestCreate(BaseModel):
    property_id: int
    category: MaintenanceCategory
    urgency: MaintenanceUrgency
    title: str
    description: str | None = None
    preferred_contact_method: str | None = None
    availability_notes: str | None = None


class MaintenanceRequestUpdate(BaseModel):
    request_status: MaintenanceRequestStatus | None = None
    assigned_agent_id: int | None = None
    work_order_status: WorkOrderStatus | None = None
    priority: str | None = None
    estimated_cost: float | None = Field(default=None, ge=0)
    actual_cost: float | None = Field(default=None, ge=0)
    scheduled_for: datetime | None = None
    completed_at: datetime | None = None
    closed_at: datetime | None = None
    completion_notes: str | None = None


class MaintenanceRequest(BaseModel):
    id: int
    property_id: int
    lease_id: int | None = None
    owner_id: int
    tenant_user_id: int | None = None
    category: MaintenanceCategory
    urgency: MaintenanceUrgency
    title: str
    description: str | None = None
    preferred_contact_method: str | None = None
    availability_notes: str | None = None
    request_status: MaintenanceRequestStatus
    assigned_agent_id: int | None = None
    work_order_status: WorkOrderStatus | None = None
    priority: str | None = None
    estimated_cost: float | None = None
    actual_cost: float | None = None
    scheduled_for: datetime | None = None
    completed_at: datetime | None = None
    closed_at: datetime | None = None
    completion_notes: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

