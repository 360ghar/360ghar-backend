"""REP-I parser tests against a captured HRERA filing.

The fixture is the real page for DLF Privana West (portal project 2779,
RERA-GRG-1540-2024), so the expected values below are what the portal actually
serves. If the portal changes its markup, these tests fail rather than letting a
silently emptier filing through.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.data_hub.rera_project_detail import (
    derive_stage,
    derive_units_per_acre,
    parse_rep_i,
)

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "hrera"
    / "rep_i_privana_west.html"
)
PORTAL_PROJECT_ID = "2779"


@pytest.fixture(scope="module")
def filing():
    return parse_rep_i(FIXTURE.read_text(encoding="utf-8"), portal_project_id=PORTAL_PROJECT_ID)


def test_filing_parses_without_fatal_errors(filing) -> None:
    assert filing.ok, filing.errors
    assert filing.errors == []


def test_only_the_irregular_quarterly_table_is_reported_as_degraded(filing) -> None:
    stages = {note["stage"] for note in filing.notes}
    assert stages == {"part_c_expenditure"}
    assert "did not carry four quarter columns" in filing.notes[0]["message"]


def test_header_carries_the_filing_identity(filing) -> None:
    assert filing.header["temp_project_id"] == "RERA-GRG-PROJ-1540-2024"
    assert filing.header["project_name"] == "DLF PRIVANA WEST"
    assert filing.header["promoter_name"] == "DLF LIMITED"
    assert filing.header["promoter_cin"] == "L70101HR1963PLC002484"
    assert filing.header["submitted_on"] == date(2024, 2, 29)
    assert filing.header["district"] == "GURUGRAM"
    assert filing.header["tehsil"] == "MANESAR"
    assert filing.header["project_type"] == "NEW"
    # The registered address is the row below the name, not the name itself.
    assert filing.header["promoter_address"].startswith("3RD FLOOR, SHOPPING MALL")
    assert filing.header["promoter_address"] != filing.header["promoter_name"]


def test_profile_matches_the_filed_figures(filing) -> None:
    profile = filing.profile
    assert profile["portal_project_id"] == PORTAL_PROJECT_ID
    assert profile["proposed_far"] == Decimal("0.461")
    assert profile["permissible_far"] == Decimal("1.25")
    assert profile["licensed_land_acres"] == Decimal("116.29625")
    assert profile["land_area_sqm"] == Decimal("50876.998")
    assert profile["total_units"] == 795
    assert profile["towers"] == 5
    assert profile["construction_start_date"] == date(2024, 10, 1)
    assert profile["proposed_completion_date"] == date(2031, 12, 31)
    # 795 units over 12.572 acres, derived from the filed land area.
    assert profile["units_per_acre"] == Decimal("63.24")


def test_fields_hrera_does_not_publish_stay_unset(filing) -> None:
    """No price, floor count, or coordinate is invented from a neighbouring field."""
    for key in ("launch_price_per_sqft", "current_price_per_sqft", "latitude", "longitude"):
        assert key not in filing.profile, key
    assert "floors" not in filing.profile


def test_land_usage_has_twelve_particulars_with_shares(filing) -> None:
    assert len(filing.land_usage) == 12
    by_particular = {row["particular"]: row for row in filing.land_usage}
    assert by_particular["PLOTS TO BE SOLD"]["area_sqm"] == Decimal("0")
    apartments = by_particular["LAND AREA TO BE USED FOR CONSTRUCTION OF APARTMENTS"]
    assert apartments["area_sqm"] == Decimal("7131.78")
    # Percentages are shares of the 50876.907 sq m total the filing states.
    assert apartments["percentage"] == Decimal("14.02")
    assert all(row["percentage"] is not None for row in filing.land_usage)
    assert all(row["area_acres"] is not None for row in filing.land_usage)


def test_cost_breakdown_is_converted_from_lakhs_to_rupees(filing) -> None:
    cost = filing.cost
    assert cost["total_cost"] == Decimal("283709.67") * 100000
    assert cost["land_cost"] == Decimal("34286.67") * 100000
    assert cost["construction_cost"] == Decimal("220544.84") * 100000
    assert cost["infrastructure_cost"] == Decimal("11607.62") * 100000
    assert cost["other_cost"] == Decimal("17270.53") * 100000
    # The filing's own components sum to 0.01 lakh less than its stated total,
    # so the parts are checked against the total rather than assumed to match it.
    parts = (
        cost["land_cost"] + cost["construction_cost"] + cost["infrastructure_cost"] + cost["other_cost"]
    )
    assert abs(parts - cost["total_cost"]) <= Decimal("0.01") * 100000


def test_documents_cover_both_upload_tables(filing) -> None:
    # 87 filed with the application plus 40 uploaded after registration.
    assert len(filing.documents) == 127
    assert [row["ordinal"] for row in filing.documents] == list(range(1, 128))
    first = filing.documents[0]
    assert first["description"].startswith("CERTIFICATE FROM A CHARTERED ACCOUNTANT")
    assert first["uploaded_on"] == date(2024, 2, 13)
    assert first["view_url"].startswith("https://haryanarera.gov.in/")
    last = filing.documents[-1]
    assert last["description"] == "Addendum uploaded"
    assert last["uploaded_on"] == date(2026, 7, 3)
    # Each row carries its own link, not the first link in the table.
    urls = [row["view_url"] for row in filing.documents if row["view_url"]]
    assert len(urls) == len(set(urls)) == len(filing.documents)


def test_people_cover_company_roles_and_licensees(filing) -> None:
    roles: dict[str, int] = {}
    for person in filing.people:
        roles[person["role"]] = roles.get(person["role"], 0) + 1
    assert roles == {
        "chairman": 1,
        "managing_director": 1,
        "director": 11,
        "authorised_representative": 1,
        "licensee": 27,
    }
    chairman = next(p for p in filing.people if p["role"] == "chairman")
    assert chairman["name"] == "MR RAJIV SINGH"
    assert chairman["address"].startswith("16 Aurangzeb Road")
    assert chairman["email"] == "haryanarera@dlf.in"
    assert chairman["photo_url"].startswith("https://haryanarera.gov.in/relation_cert/")
    assert chairman["phones"]


def test_only_the_last_four_pan_characters_are_kept(filing) -> None:
    pans = [person.get("pan_last4") for person in filing.people if person["role"] != "licensee"]
    assert all(pan is None or len(pan) == 4 for pan in pans)
    chairman = next(p for p in filing.people if p["role"] == "chairman")
    # The filing serves "XXXX665G"; only "665G" may be stored.
    assert chairman["pan_last4"] == "665G"
    assert not any("pan" == key for person in filing.people for key in person)


def test_licensees_are_recorded_with_their_land_addresses(filing) -> None:
    licensees = [p for p in filing.people if p["role"] == "licensee"]
    assert licensees[0]["name"] == "M/S DLF LIMITED"
    assert licensees[0]["address"].startswith("1ST FLOOR SHOPPING MALL COMPLEX")
    assert licensees[-1]["name"] == "M/S GURGAON ONE REALITY PVT. LTD."


def test_facilities_carry_cost_and_status(filing) -> None:
    assert len(filing.facilities) == 18
    first = filing.facilities[0]
    assert first["facility"] == "INTERNAL ROADS AND PAVEMENTS"
    assert first["estimated_cost"] == Decimal("1745.67") * 100000
    assert first["status"] == "YET TO BE PREPARED"
    zero_cost = next(f for f in filing.facilities if f["facility"] == "SCHOOL")
    assert zero_cost["estimated_cost"] == Decimal("0")
    assert zero_cost["status"] == "AS PER PROJECT REPORT"


def test_nocs_name_the_provider_agency(filing) -> None:
    assert len(filing.nocs) == 5
    assert {noc["facility"] for noc in filing.nocs} == {
        "ROADS",
        "WATER SUPPLY",
        "ELECTRICITY",
        "SEWAGE DISPOSAL",
        "STORM WATER DRAINAGE",
    }
    assert all(noc["provider_agency"] == "GMDA" for noc in filing.nocs)
    assert all(noc["approved"] is True for noc in filing.nocs)


def test_unit_configs_keep_both_areas_of_the_same_type(filing) -> None:
    # Both rows share a unit type, so the type alone cannot be the key.
    assert len(filing.unit_configs) == 2
    assert [row["ordinal"] for row in filing.unit_configs] == [1, 2]
    assert {row["unit_type"] for row in filing.unit_configs} == {
        "Apartment/Shops/Other Buildings"
    }
    assert [row["carpet_area_sqm"] for row in filing.unit_configs] == [
        Decimal("198.475"),
        Decimal("330.881"),
    ]
    assert [row["units"] for row in filing.unit_configs] == [785, 10]
    assert sum(row["units"] for row in filing.unit_configs) == filing.profile["total_units"]


def test_statutory_approvals_include_plan_approvals_and_utilities(filing) -> None:
    statutory = filing.statutory
    assert statutory["licence_number"] == "DTCP 219 of 2023"
    assert statutory["licence_date"] == date(2023, 10, 25)
    assert statutory["loi_date"] == date(2023, 9, 8)
    assert statutory["loi_obtained"] is True
    assert statutory["water_available"] is True
    # The portal spells this row "STROM"; it must not be read as the water row.
    assert statutory["storm_water_available"] is True
    assert statutory["sewerage_available"] is True
    assert statutory["plan_approvals"]["Lay out Plan"] is True
    assert statutory["plan_approvals"]["Detail of covered area achieved FAR"] is True
    assert len(statutory["plan_approvals"]) == 10
    assert all(statutory["plan_approvals"].values())


def test_bank_account_is_captured_in_full(filing) -> None:
    account = filing.bank_account
    assert account["bank_name"] == "ICICI BANK LIMITED"
    assert account["branch_name"].startswith("QUTAB PLAZA")
    assert account["account_number"] == "017705014520"
    assert account["ifsc"] == "ICIC0000177"
    assert account["micr"] == "110229030"
    assert account["branch_code"] == "000177"
    assert account["operators"].startswith("Mr. Puneet Rakheja")


def test_specifications_are_project_scoped_lines(filing) -> None:
    assert len(filing.specifications) == 23
    assert all(row["scope"] == "project" for row in filing.specifications)
    assert all(row["unit_type"] == "all" for row in filing.specifications)
    by_key = {row["spec_key"]: row["spec_value"] for row in filing.specifications}
    assert by_key["FLOORING DETAILS OF VARIOUS PARTS OF HOUSE"] == "TILES/MARBLE/GRANITE/LAMINATED WOODEN"
    assert by_key["CNG PIPE LINE"] == "GAS PIPE LINE PROVISION ONLY"


def test_quarterly_expenditure_keeps_only_complete_year_rows(filing) -> None:
    """The portal serves later years as merged one-cell rows; those are not guessed at."""
    assert filing.expenditure
    assert {row["quarter"] for row in filing.expenditure} == {1, 2, 3, 4}
    assert {row["category"] for row in filing.expenditure} == {"infrastructure"}
    assert {row["year"] for row in filing.expenditure} == {2030}
    water = next(
        row
        for row in filing.expenditure
        if row["particular"] == "Water Supply System"
    )
    assert water["quarter"] == 1
    assert water["amount"] == Decimal("60") * 100000
    # Every other quarterly table on the page is unreadable and is reported.
    assert any(note["stage"] == "part_c_expenditure" for note in filing.notes)


# ---------------------------------------------------------------------------
# Fail-loudly behaviour
# ---------------------------------------------------------------------------


def test_empty_html_reports_every_missing_section() -> None:
    filing = parse_rep_i("<html><body><p>maintenance</p></body></html>", portal_project_id="1")
    assert filing.ok is False
    stages = {error["stage"] for error in filing.errors}
    assert {
        "header",
        "part_a",
        "part_b",
        "part_c",
        "part_c_land_usage",
        "part_c_nocs",
        "part_c_facilities",
        "part_c_schedule",
        "part_c_unit_configs",
        "part_d",
        "part_e_plan_approvals",
        "part_e_statutory",
        "part_h",
        "documents",
    } <= stages


def test_a_filing_without_a_project_name_is_rejected() -> None:
    filing = parse_rep_i(
        "<html><body><table><tr><td>Part - A</td></tr></table></body></html>",
        portal_project_id="1",
    )
    assert filing.ok is False
    assert any(error["error_type"] == "ProjectNameNotFound" for error in filing.errors)


# ---------------------------------------------------------------------------
# Derived values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("register_status", "start", "completion", "today", "expected"),
    [
        ("completed", date(2024, 1, 1), date(2024, 6, 1), date(2026, 1, 1), "completed"),
        (None, date(2026, 6, 1), date(2030, 1, 1), date(2026, 1, 1), "pre_launch"),
        (None, date(2024, 10, 1), date(2031, 12, 31), date(2026, 1, 1), "under_construction"),
        (None, date(2024, 10, 1), date(2026, 4, 1), date(2026, 1, 1), "near_possession"),
        # The filed completion date has passed but the register still lists the
        # project, so the stage is unknown rather than assumed.
        ("registered", date(2024, 10, 1), date(2025, 1, 1), date(2026, 1, 1), None),
        ("registered", None, date(2031, 1, 1), date(2026, 1, 1), None),
        ("registered", None, None, date(2026, 1, 1), None),
    ],
)
def test_stage_follows_filed_dates_only(
    register_status, start, completion, today, expected
) -> None:
    assert (
        derive_stage(
            register_status=register_status,
            construction_start_date=start,
            proposed_completion_date=completion,
            today=today,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("units", "land_sqm", "expected"),
    [
        (795, Decimal("50876.998"), Decimal("63.24")),
        (None, Decimal("50876.998"), None),
        (795, None, None),
        (795, Decimal("0"), None),
    ],
)
def test_units_per_acre_needs_both_inputs(units, land_sqm, expected) -> None:
    assert derive_units_per_acre(units, land_sqm) == expected
