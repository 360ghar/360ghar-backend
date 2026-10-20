from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ExpenseCategory
from app.schemas.base import Money, NotNullable, PatchModel, UtcDateTime, WriteModel


class ExpenseCreate(WriteModel):
    owner_id: int | None = Field(default=None, description="Owner id (agent/admin only)")
    property_id: int
    category: ExpenseCategory
    title: str | None = Field(default=None, max_length=200)
    amount: Annotated[Money, Field(gt=0)]
    expense_date: date
    description: str | None = None
    notes: str | None = None
    receipt_document_id: int | None = None


class ExpenseUpdate(PatchModel):
    property_id: Annotated[int | None, NotNullable] = None
    category: Annotated[ExpenseCategory | None, NotNullable] = None
    title: str | None = Field(default=None, max_length=200)
    amount: Annotated[Money | None, NotNullable, Field(gt=0)] = None
    expense_date: Annotated[date | None, NotNullable] = None
    description: str | None = None
    notes: str | None = None
    receipt_document_id: int | None = None


class Expense(BaseModel):
    id: int
    property_id: int
    property_name: str | None = None
    owner_id: int
    category: ExpenseCategory
    title: str | None = None
    amount: Money
    expense_date: date
    description: str | None = None
    notes: str | None = None
    receipt_document_id: int | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None

    model_config = ConfigDict(from_attributes=True)
