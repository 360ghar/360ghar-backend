"""Tests for MCP price formatting functions."""

from __future__ import annotations

from app.mcp.chatgpt.response_formatter import (
    format_price,
    format_property_detail_summary,
    format_property_list_summary,
)


class TestFormatPrice:
    """Tests for the format_price helper."""

    def test_small_amount(self):
        assert format_price(19422) == "19,422"

    def test_thousands(self):
        assert format_price(50000) == "50,000"

    def test_lakh(self):
        assert format_price(150000) == "1.50 L"

    def test_multiple_lakhs(self):
        assert format_price(2500000) == "25.00 L"

    def test_crore(self):
        assert format_price(25000000) == "2.50 Cr"

    def test_exact_one_lakh(self):
        assert format_price(100000) == "1.00 L"

    def test_exact_one_crore(self):
        assert format_price(10000000) == "1.00 Cr"

    def test_monthly_rent_small(self):
        assert format_price(19422, is_monthly_rent=True) == "19,422"

    def test_monthly_rent_large(self):
        # Even large rent amounts should use comma formatting, not lakh/crore
        assert format_price(150000, is_monthly_rent=True) == "150,000"

    def test_monthly_rent_very_large(self):
        assert format_price(500000, is_monthly_rent=True) == "500,000"

    def test_zero(self):
        assert format_price(0) == "0"

    def test_float_value(self):
        assert format_price(19422.50) == "19,422"  # Python rounds .5 to even (banker's rounding)


class TestFormatPropertyDetailSummary:
    """Tests for property detail summary formatting."""

    def test_rent_property_shows_monthly(self):
        data = {
            "title": "Test Apartment",
            "locality": "Koramangala",
            "city": "Bengaluru",
            "bedrooms": 3,
            "bathrooms": 2,
            "monthly_rent": 25000,
            "purpose": "rent",
        }
        summary = format_property_detail_summary(data)
        assert "25,000/month" in summary

    def test_sale_property_shows_price(self):
        data = {
            "title": "Test Villa",
            "locality": "Whitefield",
            "city": "Bengaluru",
            "bedrooms": 4,
            "base_price": 25000000,
            "purpose": "buy",
        }
        summary = format_property_detail_summary(data)
        assert "2.50 Cr" in summary

    def test_rent_property_no_lakh_notation(self):
        """Bug fix: rent of 150000 should show '150,000/month' not '1.50 L/month'."""
        data = {
            "title": "Premium Flat",
            "locality": "Bandra",
            "city": "Mumbai",
            "monthly_rent": 150000,
            "purpose": "rent",
        }
        summary = format_property_detail_summary(data)
        assert "150,000/month" in summary
        assert "L/month" not in summary


class TestFormatPropertyListSummary:
    """Tests for property list summary formatting."""

    def test_empty_results_show_suggestions(self):
        summary = format_property_list_summary([], 0, {"city": "Agra"})
        assert "No properties found" in summary
        assert "360Ghar" in summary

    def test_empty_results_no_filters(self):
        summary = format_property_list_summary([], 0, {})
        assert "No properties found" in summary
        assert "expanding" in summary.lower()

    def test_nonempty_results(self):
        properties = [
            {"base_price": 5000000, "property_type": "apartment", "city": "Delhi"},
            {"base_price": 8000000, "property_type": "apartment", "city": "Delhi"},
        ]
        summary = format_property_list_summary(properties, 2, {})
        assert "Found 2" in summary
