"""
Tests for app.services.pm_expenses module.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BadRequestException
from app.models.enums import ExpenseCategory, UserRole
from app.models.users import User
from app.services.pm_expenses import create_expense


class TestCreateExpense:
    """Tests for create_expense function."""

    @pytest.mark.asyncio
    async def test_negative_amount_rejected(self):
        """Negative expense amount raises BadRequestException."""
        db = AsyncMock()
        actor = User(
            id=1,
            supabase_user_id="abc",
            role=UserRole.admin.value,
            is_active=True,
        )

        with patch("app.services.pm_expenses.assert_can_manage_owner_portfolio", new_callable=AsyncMock):
            with patch("app.services.pm_expenses.assert_can_access_property", new_callable=AsyncMock):
                with pytest.raises(BadRequestException, match="amount must be > 0"):
                    await create_expense(
                        db,
                        actor=actor,
                        owner_id=1,
                        property_id=1,
                        category=ExpenseCategory.maintenance,
                        amount=-500.0,
                        expense_date=date.today(),
                    )

    @pytest.mark.asyncio
    async def test_zero_amount_rejected(self):
        """Zero expense amount raises BadRequestException."""
        db = AsyncMock()
        actor = User(
            id=1,
            supabase_user_id="abc",
            role=UserRole.admin.value,
            is_active=True,
        )

        with patch("app.services.pm_expenses.assert_can_manage_owner_portfolio", new_callable=AsyncMock):
            with patch("app.services.pm_expenses.assert_can_access_property", new_callable=AsyncMock):
                with pytest.raises(BadRequestException, match="amount must be > 0"):
                    await create_expense(
                        db,
                        actor=actor,
                        owner_id=1,
                        property_id=1,
                        category=ExpenseCategory.utilities,
                        amount=0,
                        expense_date=date.today(),
                    )

    @pytest.mark.asyncio
    async def test_valid_expense_creation(self):
        """Valid expense is created successfully."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        actor = User(
            id=1,
            supabase_user_id="abc",
            role=UserRole.admin.value,
            is_active=True,
        )

        mock_prop = MagicMock()
        mock_prop.owner_id = 1

        with patch("app.services.pm_expenses.assert_can_manage_owner_portfolio", new_callable=AsyncMock):
            with patch("app.services.pm_expenses.assert_can_access_property", new_callable=AsyncMock, return_value=mock_prop):
                expense = await create_expense(
                    db,
                    actor=actor,
                    owner_id=1,
                    property_id=1,
                    category=ExpenseCategory.maintenance,
                    amount=5000.0,
                    expense_date=date.today(),
                    description="Plumbing repair",
                )
                db.add.assert_called_once()
                db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recurring_expense(self):
        """Recurring expense can be created with recurrence rule."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        actor = User(
            id=1,
            supabase_user_id="abc",
            role=UserRole.admin.value,
            is_active=True,
        )

        mock_prop = MagicMock()
        mock_prop.owner_id = 1

        with patch("app.services.pm_expenses.assert_can_manage_owner_portfolio", new_callable=AsyncMock):
            with patch("app.services.pm_expenses.assert_can_access_property", new_callable=AsyncMock, return_value=mock_prop):
                expense = await create_expense(
                    db,
                    actor=actor,
                    owner_id=1,
                    property_id=1,
                    category=ExpenseCategory.hoa,
                    amount=2000.0,
                    expense_date=date.today(),
                    is_recurring=True,
                    recurrence_rule={"frequency": "monthly"},
                )
                db.add.assert_called_once()
