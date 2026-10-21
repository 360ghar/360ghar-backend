"""Number matching, validator rules and near-duplicate scoring. No database."""

from __future__ import annotations

import copy

import pytest

from app.services.content import dedupe, validator
from app.services.content.facts import MIN_FACTS_FOR_INDEX, Fact, FactSheet
from app.services.content.numbers import allowed_numbers, extract_amounts, matches


def make_sheet(kind: str = "locality") -> FactSheet:
    sheet = FactSheet(kind, "sector-56", "Sector 56", "Gurugram")
    sheet.add(Fact("place", "Place", "Sector 56 is a sector in Gurugram, Haryana", "360 Ghar", "2026-10-01", "geo"))
    sheet.add(Fact("median_sale", "Median", "₹1.25 crore", "listings", "2026-10-01", "price"))
    sheet.add(Fact("range", "Range", "₹85 lakh to ₹3.50 crore", "listings", "2026-10-01", "price"))
    sheet.add(Fact("psf", "Per sq ft", "₹9,000 per sq ft", "listings", "2026-10-01", "price"))
    sheet.add(Fact("circle", "Circle rate", "₹45,000 per sq yd", "HR", "2024-04-01", "circle_rate"))
    sheet.add(Fact("lm", "Nearby", "Sector 55-56 Metro Station (metro), 0.5 km", "360 Ghar", None, "geo"),
              "Sector 55-56 Metro Station", "Golf Course Road")
    return sheet


SUMMARY = (
    "Sector 56 in Gurugram has homes with a median listed price of ₹1.25 crore and listings from "
    "₹85 lakh to ₹3.50 crore. The Sector 55-56 Metro Station is 0.5 km away, and the circle rate is "
    "₹45,000 per sq yd. Listings quote about ₹9,000 per sq ft, so buyers can compare budgets for "
    "ready homes near Golf Course Road."
)


def good_locality() -> dict:
    return {
        "summary": SUMMARY,
        "highlights": ["Median listed price is ₹1.25 crore", "Metro station 0.5 km away", "Circle rate ₹45,000 per sq yd"],
        "faqs": [
            {"question": q, "answer": a}
            for q, a in zip(
                ["What is the price range?", "What is the median?", "What is the circle rate?", "Is a metro near?"],
                (
                ["Listings run from ₹85 lakh to ₹3.50 crore.", "The median is ₹1.25 crore.",
                 "The circle rate is ₹45,000 per sq yd.", "The metro station is 0.5 km away."]),
                strict=True,
            )
        ],
        "meta_description": "Sector 56, Gurugram: prices, circle rate and nearby metro.",
    }


def test_extract_amounts_units_and_digits():
    values = {a.value for a in extract_amounts("₹1.2 crore, 85 lakhs, 1,25,000, १२ लाख, 2.5 - 8 crore")}
    assert {1.2e7, 8.5e6, 125000, 1.2e6, 2.5e7, 8e7} <= values


def test_matches_within_half_percent():
    allowed = {10_000_000.0}
    assert matches(10_040_000.0, allowed)
    assert not matches(10_060_000.0, allowed)


def test_area_conversions_are_allowed():
    allowed = allowed_numbers(["1,800 sq ft", "₹45,000 per sq yd"])
    assert matches(200.0, allowed)  # 1,800 sq ft is 200 sq yd
    assert matches(5000.0, allowed)  # 45,000 per sq yd is 5,000 per sq ft
    assert not matches(333.0, allowed)


def test_good_output_passes():
    result = validator.validate(good_locality(), make_sheet(), "en")
    assert result.ok, result.errors


def test_invented_number_fails():
    out = good_locality()
    out["highlights"][0] = "Median listed price is ₹1.40 crore"
    result = validator.validate(out, make_sheet(), "en")
    assert any("1.40 crore" in e for e in result.errors)


def test_lakh_crore_conversion_passes():
    out = good_locality()
    out["highlights"][0] = "Median listed price is ₹125 lakh"
    assert validator.validate(out, make_sheet(), "en").ok


def test_devanagari_digits_checked():
    out = good_locality()
    out["highlights"][0] = "औसत कीमत ₹१४० लाख है"
    assert not validator.validate(out, make_sheet(), "hi").ok
    out["highlights"][0] = "औसत कीमत ₹१२५ लाख है"
    assert validator.validate(out, make_sheet(), "hi").ok


def test_unknown_proper_noun_fails():
    out = good_locality()
    out["highlights"][1] = "Close to the Taj Mahal and Metro station"
    errors = validator.validate(out, make_sheet(), "en").errors
    assert any("'Taj'" in e for e in errors)


def test_name_at_sentence_start_is_grammar():
    out = good_locality()
    out["highlights"][1] = "Metro station is 0.5 km away"
    assert validator.validate(out, make_sheet(), "en").ok


@pytest.mark.parametrize(
    "phrase",
    ["Guaranteed returns for buyers", "This will appreciate quickly", "The best sector in Gurugram",
     "A risk-free choice", "गारंटी के साथ"],
)
def test_speculative_language_rejected(phrase):
    out = good_locality()
    out["highlights"][2] = phrase
    errors = validator.validate(out, make_sheet(), "en").errors
    assert any("banned claim" in e for e in errors)


def test_summary_word_count_bounds():
    out = good_locality()
    out["summary"] = "Too short."
    assert any("summary has" in e for e in validator.validate(out, make_sheet(), "en").errors)
    out["summary"] = " ".join(["word"] * 61)
    assert any("summary has 61" in e for e in validator.validate(out, make_sheet(), "en").errors)


def test_faq_count_bounds():
    out = good_locality()
    out["faqs"] = out["faqs"][:3]
    assert any("faqs needs 4 to 6" in e for e in validator.validate(out, make_sheet(), "en").errors)
    out["faqs"] = copy.deepcopy(good_locality()["faqs"]) * 2
    assert any("faqs needs 4 to 6" in e for e in validator.validate(out, make_sheet(), "en").errors)


def test_missing_field_reported():
    out = good_locality()
    del out["faqs"]
    assert "missing fields: faqs" in validator.validate(out, make_sheet(), "en").errors[0]


def test_fact_threshold_needs_count_and_key_fact():
    sheet = make_sheet()
    assert sheet.fact_count == 6 == MIN_FACTS_FOR_INDEX
    assert sheet.meets_threshold
    sheet.facts = [f for f in sheet.facts if f.group not in ("price", "circle_rate", "rera")]
    assert not sheet.key_fact and not sheet.meets_threshold
    short = make_sheet()
    short.facts = short.facts[:5]
    assert not short.meets_threshold


def test_facts_hash_ignores_as_of_but_not_values():
    a, b = make_sheet(), make_sheet()
    b.facts[0] = Fact("place", "Place", "Sector 56 is a sector in Gurugram, Haryana", "360 Ghar", "2026-11-01", "geo")
    assert a.facts_hash() == b.facts_hash()
    b.facts[1] = Fact("median_sale", "Median", "₹1.30 crore", "listings", "2026-10-01", "price")
    assert a.facts_hash() != b.facts_hash()


def test_dedupe_thresholds():
    text = "one two three four five six seven eight nine ten eleven twelve"
    assert dedupe.jaccard(dedupe.shingles(text), dedupe.shingles(text)) == 1.0
    assert dedupe.decision(0.5) == "reject"
    assert dedupe.decision(0.49) == "review"
    assert dedupe.decision(0.35) == "review"
    assert dedupe.decision(0.34) == "ok"
    score, twin = dedupe.max_similarity(text, {"a": "completely different words here today", "b": text})
    assert (score, twin) == (1.0, "b")
    assert dedupe.max_similarity(text, {}) == (0.0, None)
