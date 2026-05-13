from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, InsufficientPermissionsError, NotFoundException
from app.models.enums import ExpenseCategory, UserRole
from app.models.pm_finance import Expense
from app.models.users import User
from app.services.pm_authz import assert_can_access_property, assert_can_manage_owner_portfolio


async def create_expense(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int,
    property_id: int,
    category: ExpenseCategory,
    amount: float,
    expense_date: date,
    description: str | None = None,
    notes: str | None = None,
    receipt_document_id: int | None = None,
    is_recurring: bool = False,
    recurrence_rule: dict | None = None,
    next_due_date: date | None = None,
) -> Expense:
    if amount <= 0:
        raise BadRequestException(detail="amount must be > 0")

    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)
    prop = await assert_can_access_property(db, actor=actor, property_id=property_id)
    if prop.owner_id != owner_id and actor.role != UserRole.admin.value:
        raise BadRequestException(detail="property_id does not belong to owner_id")

    expense = Expense(
        property_id=property_id,
        owner_id=owner_id,
        category=category,
        amount=float(amount),
        expense_date=expense_date,
        description=description,
        notes=notes,
        receipt_document_id=receipt_document_id,
        is_recurring=bool(is_recurring),
        recurrence_rule=recurrence_rule,
        next_due_date=next_due_date,
    )
    db.add(expense)
    await db.flush()
    await db.refresh(expense)
    return expense


async def list_expenses(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int | None = None,
    property_id: int | None = None,
    category: ExpenseCategory | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Expense]:
    if actor.role == UserRole.user.value:
        owner_id = actor.id
    elif actor.role == UserRole.agent.value:
        if owner_id is None:
            raise InsufficientPermissionsError("owner_id is required for agents")
    if owner_id is not None:
        await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)

    stmt = select(Expense)
    if owner_id is not None:
        stmt = stmt.where(Expense.owner_id == owner_id)
    if property_id is not None:
        stmt = stmt.where(Expense.property_id == property_id)
    if category is not None:
        stmt = stmt.where(Expense.category == category)
    if start_date is not None:
        stmt = stmt.where(Expense.expense_date >= start_date)
    if end_date is not None:
        stmt = stmt.where(Expense.expense_date <= end_date)

    stmt = stmt.order_by(Expense.expense_date.desc()).offset(offset).limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def update_expense(
    db: AsyncSession,
    *,
    actor: User,
    expense_id: int,
    property_id: int | None = None,
    category: ExpenseCategory | None = None,
    amount: float | None = None,
    expense_date: date | None = None,
    description: str | None = None,
    notes: str | None = None,
    receipt_document_id: int | None = None,
    is_recurring: bool | None = None,
    recurrence_rule: dict | None = None,
    next_due_date: date | None = None,
) -> Expense:
    expense = await db.get(Expense, expense_id)
    if not expense:
        raise NotFoundException(detail="Expense not found")

    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=expense.owner_id)

    if property_id is not None and property_id != expense.property_id:
        prop = await assert_can_access_property(db, actor=actor, property_id=property_id)
        if prop.owner_id != expense.owner_id and actor.role != UserRole.admin.value:
            raise BadRequestException(detail="property_id does not belong to owner_id")
        expense.property_id = property_id

    if category is not None:
        expense.category = category
    if amount is not None:
        if amount <= 0:
            raise BadRequestException(detail="amount must be > 0")
        expense.amount = float(amount)
    if expense_date is not None:
        expense.expense_date = expense_date
    if description is not None:
        expense.description = description
    if notes is not None:
        expense.notes = notes
    if receipt_document_id is not None:
        expense.receipt_document_id = receipt_document_id
    if is_recurring is not None:
        expense.is_recurring = bool(is_recurring)
    if recurrence_rule is not None:
        expense.recurrence_rule = recurrence_rule
    if next_due_date is not None:
        expense.next_due_date = next_due_date

    await db.flush()
    await db.refresh(expense)
    return expense
