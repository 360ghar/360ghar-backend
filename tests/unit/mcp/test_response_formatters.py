"""Unit tests for MCP ChatGPT response formatters.

Covers every public formatter in ``app/mcp/chatgpt/response_formatter.py``:
- format_price
- format_property_list_summary
- format_property_detail_summary
- format_visits_list_summary
- format_lease_list_summary
- format_rent_status_summary
- format_dashboard_summary
- format_maintenance_list_summary
- format_tenant_rent_dues_summary
"""
from __future__ import annotations

from app.mcp.chatgpt.response_formatter import (
    format_dashboard_summary,
    format_lease_list_summary,
    format_maintenance_list_summary,
    format_price,
    format_property_detail_summary,
    format_property_list_summary,
    format_rent_status_summary,
    format_tenant_rent_dues_summary,
    format_visits_list_summary,
)

# ---------------------------------------------------------------------------
# format_price
# ---------------------------------------------------------------------------


class TestFormatPrice:
    def test_small_amount(self) -> None:
        assert format_price(19422) == "19,422"

    def test_lakh(self) -> None:
        assert format_price(150000) == "1.50 L"

    def test_crore(self) -> None:
        assert format_price(25000000) == "2.50 Cr"

    def test_monthly_rent_skips_lakh(self) -> None:
        # Monthly rent uses comma formatting regardless of magnitude
        assert format_price(150000, is_monthly_rent=True) == "150,000"
        assert format_price(500000, is_monthly_rent=True) == "500,000"
        assert "L" not in format_price(150000, is_monthly_rent=True)

    def test_zero(self) -> None:
        assert format_price(0) == "0"

    def test_exact_one_lakh(self) -> None:
        assert format_price(100000) == "1.00 L"

    def test_exact_one_crore(self) -> None:
        assert format_price(10000000) == "1.00 Cr"


# ---------------------------------------------------------------------------
# format_property_list_summary
# ---------------------------------------------------------------------------


class TestFormatPropertyListSummary:
    def test_empty_results_with_suggestions(self) -> None:
        summary = format_property_list_summary([], 0, {"city": "Agra"})
        assert "No properties found" in summary
        # Suggestions branch fires when city filter is applied
        assert "without the city filter" in summary
        assert "360Ghar" in summary

    def test_empty_results_no_filters(self) -> None:
        summary = format_property_list_summary([], 0, None)
        assert "No properties found" in summary
        # No suggestions when filters is None
        assert "Suggestions" not in summary
        assert "expanding" in summary.lower()

    def test_empty_results_with_city_filter(self) -> None:
        summary = format_property_list_summary([], 0, {"city": "Pune"})
        assert "No properties found" in summary
        assert "without the city filter" in summary

    def test_results_with_price_range(self) -> None:
        properties = [
            {"base_price": 5000000, "property_type": "apartment", "city": "Delhi", "locality": "Rohini"},
            {"base_price": 8000000, "property_type": "apartment", "city": "Delhi", "locality": "Dwarka"},
        ]
        summary = format_property_list_summary(properties, 2, {})
        assert "Found 2" in summary
        assert "50.00 L" in summary
        assert "80.00 L" in summary

    def test_results_multiple_types(self) -> None:
        properties = [
            {"base_price": 5000000, "property_type": "apartment"},
            {"base_price": 8000000, "property_type": "villa"},
        ]
        summary = format_property_list_summary(properties, 2, {})
        assert "Found 2" in summary
        # Two distinct types <= 3 → list them
        assert "apartment" in summary
        assert "villa" in summary

    def test_results_no_prices(self) -> None:
        properties = [
            {"property_type": "apartment", "city": "Delhi"},
            {"property_type": "apartment", "city": "Delhi"},
        ]
        summary = format_property_list_summary(properties, 2, {})
        assert "Found 2" in summary
        # When no prices, falls back to "various prices"
        assert "various prices" in summary


# ---------------------------------------------------------------------------
# format_property_detail_summary
# ---------------------------------------------------------------------------


class TestFormatPropertyDetailSummary:
    def test_sale_property(self) -> None:
        data = {
            "title": "Test Villa",
            "locality": "Whitefield",
            "city": "Bengaluru",
            "bedrooms": 4,
            "bathrooms": 3,
            "area_sqft": 2400,
            "base_price": 25000000,
            "purpose": "buy",
        }
        summary = format_property_detail_summary(data)
        assert "Test Villa" in summary
        assert "Whitefield, Bengaluru" in summary
        assert "4 bedrooms" in summary
        assert "3 bathrooms" in summary
        assert "2,400 sq ft" in summary
        assert "2.50 Cr" in summary
        # Sale property uses one-time price format, not /month
        assert "/month" not in summary

    def test_rent_property_uses_monthly_format(self) -> None:
        data = {
            "title": "Premium Flat",
            "locality": "Bandra",
            "city": "Mumbai",
            "monthly_rent": 150000,
            "purpose": "rent",
        }
        summary = format_property_detail_summary(data)
        assert "150,000/month" in summary
        # Bug fix: monthly rent must NOT use lakh notation
        assert "L/month" not in summary

    def test_property_no_price(self) -> None:
        data = {
            "title": "Mystery House",
            "locality": "Goa",
            "city": "Panaji",
        }
        summary = format_property_detail_summary(data)
        assert "Price on request" in summary

    def test_property_with_all_specs(self) -> None:
        data = {
            "title": "Penthouse",
            "locality": "Worli",
            "city": "Mumbai",
            "bedrooms": 5,
            "bathrooms": 4,
            "area_sqft": 3500,
            "base_price": 50000000,
            "purpose": "buy",
        }
        summary = format_property_detail_summary(data)
        # All three specs must be listed
        assert "5 bedrooms" in summary
        assert "4 bathrooms" in summary
        assert "3,500 sq ft" in summary
        assert "5.00 Cr" in summary

    def test_property_missing_location(self) -> None:
        data = {"title": "Lonely House", "base_price": 1000000}
        summary = format_property_detail_summary(data)
        assert "Unknown location" in summary


# ---------------------------------------------------------------------------
# format_visits_list_summary
# ---------------------------------------------------------------------------


class TestFormatVisitsListSummary:
    def test_no_visits(self) -> None:
        summary = format_visits_list_summary([], {"total": 0, "upcoming": 0, "completed": 0})
        assert "don't" in summary or "do not" in summary
        assert "visits scheduled" in summary

    def test_with_upcoming(self) -> None:
        visits = [{"id": 1}, {"id": 2}]
        summary = format_visits_list_summary(
            visits, {"total": 2, "upcoming": 2, "completed": 0}
        )
        assert "2 visits" in summary
        assert "2 upcoming" in summary

    def test_with_completed(self) -> None:
        visits = [{"id": 1}, {"id": 2}, {"id": 3}]
        summary = format_visits_list_summary(
            visits, {"total": 3, "upcoming": 1, "completed": 2}
        )
        assert "3 visits" in summary
        assert "1 upcoming" in summary
        assert "2 completed" in summary


# ---------------------------------------------------------------------------
# format_lease_list_summary
# ---------------------------------------------------------------------------


class TestFormatLeaseListSummary:
    def test_no_leases(self) -> None:
        summary = format_lease_list_summary([], {"active_leases": 0, "total_monthly_rent": 0})
        assert "don't" in summary or "do not" in summary
        assert "leases" in summary

    def test_active_leases(self) -> None:
        leases = [{"id": 1}, {"id": 2}]
        summary = format_lease_list_summary(
            leases, {"active_leases": 2, "total_monthly_rent": 50000}
        )
        assert "2 leases" in summary
        assert "2 active" in summary
        assert "50,000" in summary
        assert "/month" in summary


# ---------------------------------------------------------------------------
# format_rent_status_summary
# ---------------------------------------------------------------------------


class TestFormatRentStatusSummary:
    def test_all_current(self) -> None:
        charges = [{"id": 1}]
        summary = format_rent_status_summary(
            charges,
            {"total_due": 0, "total_paid": 25000, "overdue_count": 0},
        )
        assert "All rent is current" in summary
        assert "No outstanding balances" in summary

    def test_with_overdue(self) -> None:
        charges = [{"id": 1}, {"id": 2}]
        summary = format_rent_status_summary(
            charges,
            {"total_due": 30000, "total_paid": 20000, "overdue_count": 3},
        )
        assert "₹20,000" in summary  # total_paid
        assert "₹30,000" in summary  # total_due
        assert "3 overdue charges require attention" in summary


# ---------------------------------------------------------------------------
# format_dashboard_summary
# ---------------------------------------------------------------------------


class TestFormatDashboardSummary:
    def test_full_dashboard(self) -> None:
        dashboard = {
            "properties": {"total": 10, "occupied": 7, "vacant": 3},
            "rent": {"expected_monthly": 200000, "collected_this_month": 150000},
            "maintenance": {"open": 4},
        }
        summary = format_dashboard_summary(dashboard)
        assert "10 properties" in summary
        assert "7 occupied" in summary
        assert "3 vacant" in summary
        # Collection rate: 150000/200000 * 100 = 75%
        assert "75%" in summary
        assert "4 open maintenance requests" in summary

    def test_no_rent_data(self) -> None:
        dashboard = {
            "properties": {"total": 2, "occupied": 0, "vacant": 2},
            "rent": {"expected_monthly": 0, "collected_this_month": 0},
            "maintenance": {"open": 0},
        }
        summary = format_dashboard_summary(dashboard)
        assert "2 properties" in summary
        assert "0 occupied" in summary
        assert "2 vacant" in summary
        # No rent line because expected_monthly == 0
        assert "rent collected" not in summary
        # No maintenance line because open == 0
        assert "maintenance requests" not in summary

    def test_with_maintenance(self) -> None:
        dashboard = {
            "properties": {"total": 5, "occupied": 5, "vacant": 0},
            "rent": {"expected_monthly": 100000, "collected_this_month": 100000},
            "maintenance": {"open": 2},
        }
        summary = format_dashboard_summary(dashboard)
        assert "2 open maintenance requests" in summary
        # 100% collection rate
        assert "100%" in summary


# ---------------------------------------------------------------------------
# format_maintenance_list_summary
# ---------------------------------------------------------------------------


class TestFormatMaintenanceListSummary:
    def test_no_requests(self) -> None:
        summary = format_maintenance_list_summary([], {"open": 0, "urgent": 0})
        assert "No maintenance requests" in summary

    def test_with_urgent(self) -> None:
        requests = [{"id": 1}, {"id": 2}]
        summary = format_maintenance_list_summary(
            requests, {"open": 2, "urgent": 1}
        )
        assert "Found 2 maintenance requests" in summary
        assert "2 require attention" in summary  # open count
        assert "1 are marked urgent" in summary

    def test_open_only_no_urgent(self) -> None:
        requests = [{"id": 1}]
        summary = format_maintenance_list_summary(
            requests, {"open": 1, "urgent": 0}
        )
        assert "1 require attention" in summary
        assert "urgent" not in summary


# ---------------------------------------------------------------------------
# format_tenant_rent_dues_summary
# ---------------------------------------------------------------------------


class TestFormatTenantRentDuesSummary:
    def test_no_dues(self) -> None:
        charges = []
        summary = format_tenant_rent_dues_summary(charges, total_due=0, overdue_count=0)
        assert "up to date" in summary
        assert "No outstanding payments" in summary

    def test_with_dues(self) -> None:
        charges = [{"id": 1}]
        summary = format_tenant_rent_dues_summary(charges, total_due=15000, overdue_count=0)
        assert "₹15,000" in summary
        assert "outstanding rent" in summary
        # No overdue mention when overdue_count is 0
        assert "overdue" not in summary

    def test_with_overdue(self) -> None:
        charges = [{"id": 1}, {"id": 2}]
        summary = format_tenant_rent_dues_summary(charges, total_due=30000, overdue_count=2)
        assert "₹30,000" in summary
        assert "2 payment(s) are overdue" in summary
        assert "as soon as possible" in summary
