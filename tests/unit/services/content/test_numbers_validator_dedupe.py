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


def amount(text: str):
    return extract_amounts(text)[0]


def test_large_values_match_within_half_percent_small_values_exactly():
    allowed = allowed_numbers(["₹1.00 crore", "200 units", "year 2019"])
    assert matches(amount("₹1.004 crore"), allowed)
    assert not matches(amount("₹1.006 crore"), allowed)
    assert matches(amount("200 units"), allowed) and not matches(amount("201 units"), allowed)
    assert matches(amount("2019"), allowed) and not matches(amount("2020"), allowed)


def test_amounts_match_only_their_own_kind():
    allowed = allowed_numbers(["Sector 55-56 Metro Station (metro), 0.5 km"])
    assert matches(amount("0.5 km"), allowed) and matches(amount("500 metres"), allowed)
    assert not matches(amount("₹0.5 crore"), allowed)
    assert not matches(amount("0.5"), allowed)


def test_area_and_rate_conversions_go_the_right_way():
    allowed = allowed_numbers(["1,200 sq ft", "₹45,000 per sq yd"])
    assert matches(amount("133.3 sq yd"), allowed)  # 1,200 sq ft is 133.3 sq yd
    assert matches(amount("111.5 sqm"), allowed)
    assert not matches(amount("10,800 sq ft"), allowed)  # not the reverse conversion
    assert matches(amount("₹5,000 per sq ft"), allowed)  # 45,000 per sq yd
    assert matches(amount("₹45,000 per sq yd"), allowed)
    assert not matches(amount("₹45,000 per sq ft"), allowed)


def test_commas_only_group_digits():
    assert [a.value for a in extract_amounts("5,10 and 1,2")] == [5, 10, 1, 2]
    assert [a.value for a in extract_amounts("1,25,000 and 12,345.5")] == [125000, 12345.5]


def test_spelled_numbers_are_checked_like_digits():
    allowed = allowed_numbers(["3 BHK"])
    assert all(matches(a, allowed) for a in extract_amounts("three bedrooms"))
    assert not all(matches(a, allowed) for a in extract_amounts("twenty towers"))
    assert not all(matches(a, allowed) for a in extract_amounts("ten crore"))
    assert extract_amounts("one of the homes") == []


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
    sib = {"a": dedupe.shingles("completely different words here today"), "b": dedupe.shingles(text)}
    score, twin = dedupe.max_similarity(text, sib)
    assert (score, twin) == (1.0, "b")
    assert dedupe.max_similarity(text, {}) == (0.0, None)


def test_dedupe_counts_devanagari_words_whole_and_normalises_apostrophes():
    assert dedupe.shingles("सुंदर घर में आपका स्वागत है यहाँ") != set()
    assert ("सुंदर", "घर", "में", "आपका", "स्वागत") in dedupe.shingles("सुंदर घर में आपका स्वागत है")
    assert dedupe.shingles("Bangalore’s new homes are here today") == dedupe.shingles("Bangalore's new homes are here today")


def test_dedupe_text_includes_who_it_suits_and_sections():
    text = dedupe.content_text({"summary": "a", "who_it_suits": "families", "sections": [{"body": "weekly"}]})
    assert "families" in text and "weekly" in text


def test_possessive_of_an_allowed_name_is_fine_and_unknown_one_is_not():
    out = good_locality()
    out["highlights"][1] = "Gurugram's metro station is 0.5 km away"
    assert validator.validate(out, make_sheet(), "en").ok
    out["highlights"][1] = "Mumbai's metro station is 0.5 km away"
    assert any("'Mumbai'" in e for e in validator.validate(out, make_sheet(), "en").errors)


def test_sentence_start_checks_company_names_and_cities():
    out = good_locality()
    out["faqs"][0]["answer"] = "Sobha City is a larger registered project."
    assert any("'Sobha'" in e for e in validator.validate(out, make_sheet(), "en").errors)
    out["faqs"][0]["answer"] = "Mumbai is nearby."
    assert any("'Mumbai'" in e for e in validator.validate(out, make_sheet(), "en").errors)
    out["faqs"][0]["answer"] = "Listings run from ₹85 lakh to ₹3.50 crore."
    assert validator.validate(out, make_sheet(), "en").ok


def test_lakh_and_crore_words_are_not_names():
    out = good_locality()
    out["highlights"][0] = "Median listed price is ₹1.25 Crore"
    assert validator.validate(out, make_sheet(), "en").ok


def test_item_types_are_checked():
    out = good_locality()
    out["faqs"][0]["answer"] = None
    assert any("question and answer" in e for e in validator.validate(out, make_sheet(), "en").errors)
    out = good_locality()
    out["highlights"][0] = {"x": 1}
    assert any("highlights must be text" in e for e in validator.validate(out, make_sheet(), "en").errors)


@pytest.mark.parametrize("phrase", ["The finest homes", "Safest sector in town", "The most popular choice"])
def test_more_subjective_superlatives_rejected(phrase):
    out = good_locality()
    out["highlights"][2] = phrase
    assert any("banned claim" in e for e in validator.validate(out, make_sheet(), "en").errors)


def test_dates_allow_only_the_year_and_titles_add_no_numbers():
    sheet = make_sheet()
    out = good_locality()
    out["highlights"][0] = "Data from 2024"
    assert validator.validate(out, sheet, "en").ok
    out["highlights"][0] = "Data from month 10"
    assert not validator.validate(out, sheet, "en").ok


def test_inr_rounds_across_the_lakh_crore_boundary():
    from app.services.content.facts import inr, money_range

    assert inr(9_999_900) == "₹1.00 crore"
    assert inr(9_990_000) == "₹99.90 lakh"
    assert money_range("85 lakhs - 3.5 crore") == "₹85 lakh to ₹3.5 crore"
    assert money_range("15,000 - 85,000/month") == "₹15,000 to ₹85,000 per month"
    assert money_range("1.5 - 5 lakh/month") == "₹1.5 lakh to ₹5 lakh per month"


def test_range_shares_the_per_area_unit():
    allowed = allowed_numbers(["₹58,230 to ₹1.14 lakh per sq yd"])
    assert matches(amount("₹58,230 per sq yd"), allowed)
    assert matches(amount("₹1.14 lakh per sq yd"), allowed)
    assert not matches(amount("₹58,230"), allowed)


def test_rs_inside_a_word_is_not_a_currency_sign():
    assert [(a.kind, a.value) for a in extract_amounts("It offers 3 BHK with 2 bathrooms")] == [
        ("plain", 3.0), ("plain", 2.0),
    ]
    assert [(a.kind, a.value) for a in extract_amounts("Rs. 5,000 or INR 7,000")] == [
        ("money", 5000.0), ("money", 7000.0),
    ]
