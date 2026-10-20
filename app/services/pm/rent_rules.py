"""Rent charge rules as plain functions: grace period, overdue status, late fee.

No database access. Callers pass dates and amounts. Money is a Decimal inside the
service layer. A JSON number is produced only at the wire boundary (``Money`` in
``app/schemas/base.py``).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app.config import settings

DEFAULT_GRACE_DAYS = 5
# A lease moves to expiring_soon this many days before its end date.
LEASE_EXPIRY_NOTICE_DAYS = 30

ZERO_MONEY = Decimal("0.00")
_CENT = Decimal("0.01")


def money(value: object) -> Decimal:
    """Exact money amount with 2 places. A float enters through its shortest decimal text."""
    if value is None:
        return ZERO_MONEY
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def business_today() -> date:
    """Today in the business timezone (NOTIF_SCHED_TZ). The daily job and read-time overdue both use it."""
    tz = ZoneInfo(getattr(settings, "NOTIF_SCHED_TZ", None) or "Asia/Kolkata")
    return datetime.now(tz).date()


def grace_days(lease_grace_period_days: int | None) -> int:
    """Grace days for a lease. Only a missing value uses the default; 0 stays 0."""
    if lease_grace_period_days is None:
        return DEFAULT_GRACE_DAYS
    return max(int(lease_grace_period_days), 0)


def is_past_grace(due_date: date, grace: int, today: date) -> bool:
    """True after the grace period ends (the day after due_date + grace)."""
    return today > due_date + timedelta(days=grace)


def is_overdue(due_date: date, grace: int, today: date, outstanding: Decimal) -> bool:
    """A charge is overdue when a balance remains after the grace period."""
    return outstanding > ZERO_MONEY and is_past_grace(due_date, grace, today)


def late_fee(
    amount_due: object,
    late_fee_amount: object | None,
    late_fee_percentage: float | None,
) -> Decimal:
    """Fee for one overdue charge. A fixed amount wins over a percentage of the rent.

    Returns ``0.00`` when the lease has no late-fee policy. Rounded to 2 places.
    """
    if late_fee_amount is not None and money(late_fee_amount) > ZERO_MONEY:
        return money(late_fee_amount)
    if late_fee_percentage is not None and late_fee_percentage > 0:
        fee = money(amount_due) * Decimal(str(late_fee_percentage)) / Decimal(100)
        return fee.quantize(_CENT, rounding=ROUND_HALF_UP)
    return ZERO_MONEY
