from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, InsufficientPermissionsError, NotFoundException
from app.models.enums import ExpenseCategory, UserRole
from app.models.pm_finance import Expense
from app.models.properties import Property
from app.models.users import User
from app.schemas.pagination import keyset_filter, keyset_payload, keyset_sort_value
from app.schemas.pm_expense import ExpenseUpdate
from app.services.pm_authz import assert_can_access_property, assert_can_manage_owner_portfolio
from app.services.pm_documents import assert_owned_document


async def _attach_property_names(db: AsyncSession, expenses: Sequence[Any]) -> None:
    """Set a transient ``property_name`` per expense from one query."""
    ids = {e.property_id for e in expenses}
    if not ids:
        return
    rows = (await db.execute(select(Property.id, Property.title).where(Property.id.in_(ids)))).all()
    titles: dict[int, str | None] = dict(tuple(row) for row in rows)
    for expense in expenses:
        expense.property_name = titles.get(expense.property_id)


async def create_expense(
    db: AsyncSession,
    *,
    actor: User,
    owner_id: int,
    property_id: int,
    category: ExpenseCategory,
    amount: float,
    expense_date: date,
    title: str | None = None,
    description: str | None = None,
    notes: str | None = None,
    receipt_document_id: int | None = None,
) -> Expense:
    if amount <= 0:
        raise BadRequestException(detail="amount must be > 0")

    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=owner_id)
    prop = await assert_can_access_property(db, actor=actor, property_id=property_id)
    if prop.owner_id != owner_id and actor.role != UserRole.admin.value:
        raise BadRequestException(detail="property_id does not belong to owner_id")
    if receipt_document_id is not None:
        await assert_owned_document(db, document_id=receipt_document_id, owner_id=owner_id)

    expense = Expense(
        property_id=property_id,
        owner_id=owner_id,
        category=category,
        title=title,
        amount=float(amount),
        expense_date=expense_date,
        description=description,
        notes=notes,
        receipt_document_id=receipt_document_id,
    )
    db.add(expense)
    await db.flush()
    await db.refresh(expense)
    await _attach_property_names(db, [expense])
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
    cursor_payload: dict,
    limit: int = 20,
    with_total: bool = False,
) -> tuple[list[Expense], dict | None, int | None]:
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

    count_total = None
    if with_total:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        count_total = (await db.execute(count_stmt)).scalar_one()

    predicate = keyset_filter(Expense.expense_date, Expense.id, cursor_payload, descending=True)
    if predicate is not None:
        stmt = stmt.where(predicate)

    stmt = stmt.order_by(Expense.expense_date.desc(), Expense.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    next_payload = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_payload = keyset_payload(keyset_sort_value(last.expense_date), last.id)
    await _attach_property_names(db, rows)
    return rows, next_payload, count_total


async def get_expense(db: AsyncSession, *, actor: User, expense_id: int) -> Expense:
    expense = await db.get(Expense, expense_id)
    if not expense:
        raise NotFoundException(detail="Expense not found")
    await assert_can_manage_owner_portfolio(db, actor=actor, owner_id=expense.owner_id)
    return expense


async def update_expense(
    db: AsyncSession,
    *,
    actor: User,
    expense_id: int,
    body: ExpenseUpdate,
) -> Expense:
    """Apply a PATCH. Only keys the client sent change; an explicit null clears a nullable field."""
    expense = await get_expense(db, actor=actor, expense_id=expense_id)
    sent = body.model_fields_set

    if (
        "property_id" in sent
        and body.property_id is not None
        and body.property_id != expense.property_id
    ):
        prop = await assert_can_access_property(db, actor=actor, property_id=body.property_id)
        if prop.owner_id != expense.owner_id and actor.role != UserRole.admin.value:
            raise BadRequestException(detail="property_id does not belong to owner_id")
        expense.property_id = body.property_id
    if "amount" in sent and body.amount is not None:
        if body.amount <= 0:
            raise BadRequestException(detail="amount must be > 0")
        expense.amount = body.amount
    if "receipt_document_id" in sent and body.receipt_document_id is not None:
        await assert_owned_document(
            db, document_id=body.receipt_document_id, owner_id=expense.owner_id
        )

    for name in (
        "category",
        "title",
        "expense_date",
        "description",
        "notes",
        "receipt_document_id",
    ):
        if name in sent:
            setattr(expense, name, getattr(body, name))

    await db.flush()
    await db.refresh(expense)
    await _attach_property_names(db, [expense])
    return expense


async def delete_expense(db: AsyncSession, *, actor: User, expense_id: int) -> None:
    """Owner-scoped delete. Same authorization as update."""
    expense = await get_expense(db, actor=actor, expense_id=expense_id)
    await db.delete(expense)
    await db.flush()
