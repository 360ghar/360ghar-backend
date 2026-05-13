from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ExpenseCategory


class ExpenseCreate(BaseModel):
    owner_id: int | None = Field(default=None, description="Owner id (agent/admin only)")
    property_id: int
    category: ExpenseCategory
    amount: float = Field(gt=0)
    expense_date: date
    description: str | None = None
    notes: str | None = None
    receipt_document_id: int | None = None
    is_recurring: bool = False
    recurrence_rule: dict[str, Any] | None = None
    next_due_date: date | None = None


class ExpenseUpdate(BaseModel):
    property_id: int | None = None
    category: ExpenseCategory | None = None
    amount: float | None = Field(default=None, gt=0)
    expense_date: date | None = None
    description: str | None = None
    notes: str | None = None
    receipt_document_id: int | None = None
    is_recurring: bool | None = None
    recurrence_rule: dict[str, Any] | None = None
    next_due_date: date | None = None


class Expense(BaseModel):
    id: int
    property_id: int
    owner_id: int
    category: ExpenseCategory
    amount: float
    expense_date: date
    description: str | None = None
    notes: str | None = None
    receipt_document_id: int | None = None
    is_recurring: bool
    recurrence_rule: dict[str, Any] | None = None
    next_due_date: date | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
