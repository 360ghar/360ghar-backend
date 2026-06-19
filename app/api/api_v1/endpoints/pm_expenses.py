from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.dependencies.auth import get_current_active_user
from app.core.database import get_db
from app.models.enums import ExpenseCategory, UserRole
from app.schemas.pagination import CursorPage, CursorParams, build_cursor_page
from app.schemas.pm_expense import Expense as ExpenseSchema
from app.schemas.pm_expense import ExpenseCreate, ExpenseUpdate
from app.schemas.user import User as UserSchema
from app.services.pm_expenses import create_expense, list_expenses, update_expense

router = APIRouter()


@router.post(
    "",
    response_model=ExpenseSchema,
    summary="Create expense",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create": {
                            "value": {
                                "property_id": 1,
                                "category": "maintenance",
                                "amount": 1500.00,
                                "expense_date": "2026-07-01",
                                "description": "Plumbing repair in kitchen",
                            }
                        },
                    }
                }
            }
        }
    },
)
async def create_pm_expense(
    payload: ExpenseCreate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create expense."""
    target_owner_id = current_user.id
    if payload.owner_id is not None:
        if current_user.role in (UserRole.admin.value, UserRole.agent.value):
            target_owner_id = payload.owner_id
        else:
            from app.core.exceptions import InsufficientPermissionsError

            raise InsufficientPermissionsError("Only admins/agents can set owner_id")

    expense = await create_expense(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=target_owner_id,
        property_id=payload.property_id,
        category=payload.category,
        amount=payload.amount,
        expense_date=payload.expense_date,
        description=payload.description,
        notes=payload.notes,
        receipt_document_id=payload.receipt_document_id,
        is_recurring=payload.is_recurring,
        recurrence_rule=payload.recurrence_rule,
        next_due_date=payload.next_due_date,
    )
    return ExpenseSchema.model_validate(expense)


@router.get("", response_model=CursorPage[ExpenseSchema], summary="List expenses")
async def list_pm_expenses(
    owner_id: int | None = Query(None, description="Owner id (agent/admin only)"),
    property_id: int | None = Query(None),
    category: ExpenseCategory | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    page: CursorParams = Depends(),
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List expenses."""
    rows, next_payload, total = await list_expenses(
        db,
        actor=current_user,  # type: ignore[arg-type]
        owner_id=owner_id,
        property_id=property_id,
        category=category,
        start_date=start_date,
        end_date=end_date,
        cursor_payload=page.decoded(),
        limit=page.limit,
        with_total=page.include_total,
    )
    return build_cursor_page(
        [ExpenseSchema.model_validate(e) for e in rows],
        limit=page.limit,
        next_payload=next_payload,
        total=total,
    )


@router.patch("/{expense_id}", response_model=ExpenseSchema, summary="Update expense")
async def patch_pm_expense(
    expense_id: int,
    payload: ExpenseUpdate,
    current_user: UserSchema = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update expense."""
    exp = await update_expense(
        db,
        actor=current_user,  # type: ignore[arg-type]
        expense_id=expense_id,
        property_id=payload.property_id,
        category=payload.category,
        amount=payload.amount,
        expense_date=payload.expense_date,
        description=payload.description,
        notes=payload.notes,
        receipt_document_id=payload.receipt_document_id,
        is_recurring=payload.is_recurring,
        recurrence_rule=payload.recurrence_rule,
        next_due_date=payload.next_due_date,
    )
    return ExpenseSchema.model_validate(exp)
