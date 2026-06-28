"""Tests for MCP search helper operations (NLP parser, city aliases, empty results)."""

from __future__ import annotations

from app.mcp.tool_ops.search_ops import (
    build_empty_result_message,
    normalize_city,
    parse_natural_query,
)


class TestNormalizeCity:
    """Tests for city alias normalization."""

    def test_known_alias_returns_canonical(self):
        assert normalize_city("bangalore") == "Bengaluru"
        assert normalize_city("bombay") == "Mumbai"
        assert normalize_city("madras") == "Chennai"
        assert normalize_city("calcutta") == "Kolkata"
        assert normalize_city("gurgaon") == "Gurugram"

    def test_canonical_name_returns_itself(self):
        assert normalize_city("Bengaluru") == "Bengaluru"
        assert normalize_city("Mumbai") == "Mumbai"
        assert normalize_city("Delhi") == "Delhi"

    def test_case_insensitive(self):
        assert normalize_city("BANGALORE") == "Bengaluru"
        assert normalize_city("Bombay") == "Mumbai"
        assert normalize_city("GURGAON") == "Gurugram"

    def test_whitespace_trimmed(self):
        assert normalize_city("  bangalore  ") == "Bengaluru"
        assert normalize_city(" delhi ") == "Delhi"

    def test_unknown_city_returns_title_case(self):
        assert normalize_city("agra") == "Agra"
        assert normalize_city("PUNE") == "Pune"

    def test_empty_string(self):
        assert normalize_city("") == ""

    def test_common_misspellings(self):
        assert normalize_city("ahemdabad") == "Ahmedabad"
        assert normalize_city("benaras") == "Varanasi"
        assert normalize_city("cochin") == "Kochi"


class TestParseNaturalQuery:
    """Tests for NLP query parsing."""

    def test_empty_query(self):
        result = parse_natural_query("")
        assert result == {"cleaned_query": ""}

    def test_none_query(self):
        result = parse_natural_query(None)
        assert result == {"cleaned_query": ""}

    def test_bhk_extraction(self):
        result = parse_natural_query("3BHK apartment in Gurugram")
        assert result.get("bedrooms") == 3
        assert result.get("city") == "Gurugram"

    def test_bhk_with_space(self):
        result = parse_natural_query("2 BHK flat in Mumbai")
        assert result.get("bedrooms") == 2

    def test_bedroom_keyword(self):
        result = parse_natural_query("4 bedroom villa in Goa")
        assert result.get("bedrooms") == 4

    def test_price_under_crore(self):
        result = parse_natural_query("flat under 2 crore")
        assert result.get("price_max") == 20_000_000

    def test_price_under_lakh(self):
        result = parse_natural_query("apartment under 50 lakh")
        assert result.get("price_max") == 5_000_000

    def test_price_under_lakhs(self):
        result = parse_natural_query("room under 30 lakhs")
        assert result.get("price_max") == 3_000_000

    def test_price_under_k(self):
        result = parse_natural_query("rent under 30k")
        assert result.get("price_max") == 30_000

    def test_price_range(self):
        result = parse_natural_query("villa 3 crore to 5 crore")
        assert result.get("price_min") == 30_000_000
        assert result.get("price_max") == 50_000_000

    def test_property_type_flat(self):
        result = parse_natural_query("3BHK flat in Delhi")
        assert "apartment" in result.get("property_types", [])

    def test_property_type_villa(self):
        result = parse_natural_query("villa in Goa")
        assert "villa" in result.get("property_types", [])

    def test_purpose_buy(self):
        result = parse_natural_query("buy apartment in Mumbai")
        assert result.get("purpose") == "buy"

    def test_purpose_rent(self):
        result = parse_natural_query("rent flat in Bangalore")
        assert result.get("purpose") == "rent"

    def test_city_extraction(self):
        result = parse_natural_query("flat in Mumbai")
        assert result.get("city") == "Mumbai"

    def test_city_alias_extraction(self):
        result = parse_natural_query("apartment in Bangalore")
        assert result.get("city") == "Bengaluru"

    def test_full_query_decomposition(self):
        result = parse_natural_query("3BHK flat in Gurugram buy under 2 crore")
        assert result.get("bedrooms") == 3
        assert result.get("city") == "Gurugram"
        assert result.get("purpose") == "buy"
        assert result.get("price_max") == 20_000_000
        assert "apartment" in result.get("property_types", [])

    def test_cleaned_query_has_remaining_text(self):
        result = parse_natural_query("3BHK flat in Gurugram buy under 2 crore")
        # After extracting bedrooms, city, purpose, price, and property type,
        # the cleaned query should be minimal or empty
        assert isinstance(result.get("cleaned_query"), str)

    def test_simple_text_passthrough(self):
        result = parse_natural_query("swimming pool near park")
        assert result.get("cleaned_query") != ""
        assert result.get("bedrooms") is None
        assert result.get("city") is None

    def test_new_delhi_matched_before_delhi(self):
        result = parse_natural_query("flat in New Delhi")
        assert result.get("city") == "Delhi"


class TestBuildEmptyResultMessage:
    """Tests for empty result UX messages."""

    def test_basic_empty_message(self):
        msg = build_empty_result_message({})
        assert "No properties found" in msg
        assert "360Ghar" in msg

    def test_city_suggestion(self):
        msg = build_empty_result_message({"city": "Agra"}, city="Agra")
        assert "Agra" in msg
        assert "city filter" in msg.lower() or "without" in msg.lower()

    def test_price_suggestion(self):
        msg = build_empty_result_message({"price_min": 100000, "price_max": 200000})
        assert "price range" in msg.lower()

    def test_property_type_suggestion(self):
        msg = build_empty_result_message({"property_type": "villa"})
        assert "property type" in msg.lower()

    def test_multiple_suggestions(self):
        msg = build_empty_result_message(
            {"city": "Agra", "price_min": 100000},
            city="Agra",
        )
        assert "Agra" in msg
        assert "price range" in msg.lower()

    def test_expanding_message_always_present(self):
        msg = build_empty_result_message({})
        assert "expanding" in msg.lower()
