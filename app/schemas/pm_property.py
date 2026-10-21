from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ManagedPropertyStatus, PropertyPurpose, PropertyType
from app.schemas.base import NotNullable, PatchModel
from app.schemas.pm_lease import Lease as LeaseSchema
from app.schemas.property import MoneyInput, PropertyCreate, PropertyUpdate
from app.schemas.property import Property as PropertySchema


class ManagedPropertyCreate(PropertyCreate):
    """Create body for a managed property: the core listing fields plus the PM terms.

    Unknown keys fail with 422. The core listing fields go through the shared
    property create helper.
    """

    model_config = ConfigDict(extra="forbid")

    owner_id: int | None = Field(default=None, description="Owner id (admin/agent only)")
    management_status: ManagedPropertyStatus = ManagedPropertyStatus.active
    payment_due_day: int = Field(default=1, ge=1, le=28)
    grace_period_days: int = Field(default=5, ge=0, le=365)
    late_fee_policy: dict[str, Any] | None = None


class ManagedPropertyUpdate(PropertyUpdate, PatchModel):
    """PATCH body: every editable core listing field, plus the PM fields.

    Only keys the client sends are applied. An explicit null clears a nullable
    field. A null on a NOT NULL field gives 422.
    """

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str | None, NotNullable] = None
    property_type: Annotated[PropertyType | None, NotNullable] = None
    purpose: Annotated[PropertyPurpose | None, NotNullable] = None
    base_price: Annotated[MoneyInput | None, NotNullable] = None
    country: Annotated[str | None, NotNullable] = None

    management_status: Annotated[ManagedPropertyStatus | None, NotNullable] = None
    payment_due_day: Annotated[int | None, NotNullable] = Field(default=None, ge=1, le=28)
    grace_period_days: Annotated[int | None, NotNullable] = Field(default=None, ge=0, le=365)
    late_fee_policy: dict[str, Any] | None = None
    images: list[str] | None = None
    floor_plans: list[str] | None = None


class ManagedPropertyDetail(BaseModel):
    property: PropertySchema
    active_lease: LeaseSchema | None = None
