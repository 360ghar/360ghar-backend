"""HRERA FORM REP-I detail scraper and parser.

The filing page at ``view_project/project_preview_open/{portal_project_id}`` is
server-rendered: every REP-I part arrives as HTML tables, so the parse needs no
browser. Playwright is used only to reach the page, because the portal drops
plain HTTP clients on some routes.

Two rules shape this module:

* **Fail loudly, never partially.** A filing is written only when every section
  it is expected to carry parses. A section that does not parse lands in
  ``errors`` with its own stage, and the caller skips the write.
* **Never invent a value.** HRERA does not publish a price per square foot, a
  floor count, or coordinates on this page. Those columns stay null rather than
  being filled from a neighbouring field.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.data_hub.base_scraper import BaseScraper, ScrapeResult

logger = logging.getLogger(__name__)

_PORTAL_BASE = "https://haryanarera.gov.in"
_DETAIL_URL = f"{_PORTAL_BASE}/view_project/project_preview_open/{{portal_project_id}}"
_AUTHORITY = "Haryana Real Estate Regulatory Authority"

_SQM_PER_ACRE = Decimal("4046.8564224")
_LAKH = Decimal("100000")
_NEAR_POSSESSION_DAYS = 180

# How many filings one weekly run refreshes. The portal is a government service
# and the whole NCR register is far larger than one run should touch.
DEFAULT_BATCH = 25

@dataclass
class RepIFiling:
    """Everything one filing page yields, grouped by the table each part feeds.

    ``errors`` are fatal: a required section did not parse and the filing must
    not be written. ``notes`` are degraded: a section parsed, but part of it was
    unreadable. A filing with notes is still written, because the unreadable part
    is left out rather than guessed at.
    """

    portal_project_id: str
    header: dict[str, Any] = field(default_factory=dict)
    profile: dict[str, Any] = field(default_factory=dict)
    land_usage: list[dict[str, Any]] = field(default_factory=list)
    cost: dict[str, Any] = field(default_factory=dict)
    expenditure: list[dict[str, Any]] = field(default_factory=list)
    documents: list[dict[str, Any]] = field(default_factory=list)
    statutory: dict[str, Any] = field(default_factory=dict)
    facilities: list[dict[str, Any]] = field(default_factory=list)
    nocs: list[dict[str, Any]] = field(default_factory=list)
    people: list[dict[str, Any]] = field(default_factory=list)
    bank_account: dict[str, Any] = field(default_factory=dict)
    unit_configs: list[dict[str, Any]] = field(default_factory=list)
    specifications: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    notes: list[dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "portal_project_id": self.portal_project_id,
            "header": self.header,
            "profile": self.profile,
            "land_usage": self.land_usage,
            "cost": self.cost,
            "expenditure": self.expenditure,
            "documents": self.documents,
            "statutory": self.statutory,
            "facilities": self.facilities,
            "nocs": self.nocs,
            "people": self.people,
            "bank_account": self.bank_account,
            "unit_configs": self.unit_configs,
            "specifications": self.specifications,
            "errors": self.errors,
            "notes": self.notes,
        }


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _cells(row: Tag) -> list[str]:
    return [_clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["td", "th"])]


def _present(cells: list[str]) -> list[str]:
    return [cell for cell in cells if cell]


def _rows(table: Tag) -> list[list[str]]:
    return [_cells(row) for row in table.find_all("tr")]


def _non_empty_rows(table: Tag) -> list[list[str]]:
    return [row for row in (_present(cells) for cells in _rows(table)) if row]


def _decimal(value: str | None) -> Decimal | None:
    """Read the first number in a cell. ``None`` when the cell holds no number."""
    if not value:
        return None
    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", value.replace("\u00a0", " "))
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def _lakhs_to_rupees(value: str | None) -> Decimal | None:
    """The cost tables are filed in lakhs; every stored amount is in rupees."""
    amount = _decimal(value)
    return None if amount is None else amount * _LAKH


def project_slug(project_name: str | None, rera_number: str | None) -> str | None:
    """Public URL key for a project.

    The RERA number is unique, so appending it makes the slug unique by
    construction without a counter or a hash. Both parts are capped so the
    result always fits the 300-character column.
    """
    if not project_name or not rera_number:
        return None
    from app.services.data_hub.utils import generate_slug

    name_part = generate_slug(project_name)[:200]
    number_part = generate_slug(rera_number)[:80]
    slug = "-".join(part for part in (name_part, number_part) if part)
    return slug[:300] or None


def _date(value: str | None) -> date | None:
    """Read ``dd-mm-yyyy`` (the portal's form) or ``dd.mm.yyyy``."""
    if not value:
        return None
    match = re.search(r"(\d{1,2})[-./](\d{1,2})[-./](\d{2,4})", value)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _pan_last4(value: str | None) -> str | None:
    """Keep the trailing four characters of a PAN and discard the rest.

    The portal masks the identifier as ``XXXX494N`` before serving it, but a
    future layout could serve more. Truncating here means the unmasked part
    never reaches the database.
    """
    if not value:
        return None
    token = re.search(r"[A-Z0-9]{8,12}", value.upper().replace(" ", ""))
    if not token:
        return None
    return token.group(0)[-4:]


def _table_by_first_row(soup: BeautifulSoup, expected: tuple[str, ...]) -> Tag | None:
    """The first table whose leading non-empty row is ``expected``.

    Part C repeats the land-usage table inside a wrapper table, so matching the
    leading row (rather than any row) picks the clean standalone copy.
    """
    for table in soup.find_all("table"):
        rows = _non_empty_rows(table)
        if rows and tuple(rows[0]) == expected:
            return table
    return None


def _tables_by_first_row(soup: BeautifulSoup, expected: tuple[str, ...]) -> list[Tag]:
    found: list[Tag] = []
    for table in soup.find_all("table"):
        rows = _non_empty_rows(table)
        if rows and tuple(rows[0]) == expected:
            found.append(table)
    return found


def _find_table_containing(soup: BeautifulSoup, needle: str) -> Tag | None:
    for table in soup.find_all("table"):
        for row in _rows(table):
            if any(needle in cell for cell in row):
                return table
    return None


def _labelled(table: Tag, prefix: str) -> str | None:
    """Value of the first row whose leading cell starts with ``prefix``."""
    for row in _non_empty_rows(table):
        if row[0].startswith(prefix) and len(row) > 1:
            return row[1]
    return None


def _labelled_after(table: Tag, prefix: str) -> str | None:
    """Value of the first cell starting with ``prefix``, read from the same cell.

    Some parts flatten ``Label value`` into one cell instead of two.
    """
    for row in _non_empty_rows(table):
        for cell in row:
            if cell.startswith(prefix):
                remainder = cell[len(prefix) :].lstrip(" :")
                if remainder:
                    return remainder
    return None


def _first_value(table: Tag, prefix: str) -> str | None:
    """Read a labelled value whether the portal split the cells or merged them."""
    return _labelled(table, prefix) or _labelled_after(table, prefix)


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------


def _parse_header(soup: BeautifulSoup, filing: RepIFiling) -> None:
    table = _find_table_containing(soup, "Temp Project Id")
    if table is None:
        filing.errors.append(
            {
                "stage": "header",
                "error_type": "HeaderTableNotFound",
                "message": "The filing header table was not found",
            }
        )
        return
    text = " ".join(" ".join(row) for row in _non_empty_rows(table))
    temp_id = re.search(r"Temp Project Id\s*:?\s*([A-Z0-9-]+)", text)
    filing.header = {
        "temp_project_id": temp_id.group(1) if temp_id else None,
        "submitted_on": _date(_search_group(text, r"Submission Date\s*:?\s*([\d]{1,2}-[\d]{1,2}-[\d]{2,4})")),
        "applicant_type": _search_group(text, r"Applicant Type\s*:?\s*([A-Za-z]+)"),
        "project_type": _search_group(text, r"Project Type\s*:?\s*([A-Za-z]+)"),
    }


def _search_group(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


def _parse_part_a(soup: BeautifulSoup, filing: RepIFiling) -> None:
    """Company identity from Part A, plus the site address from its second page."""
    company = _find_table_containing(soup, "Name and registered address of the company")
    if company is not None:
        rows = _non_empty_rows(company)
        for index, row in enumerate(rows):
            if row[0].startswith("1. Name and registered address"):
                filing.header["promoter_name"] = row[1] if len(row) > 1 else None
                # The registered address is served in the row below the name.
                if index + 1 < len(rows) and len(rows[index + 1]) > 1:
                    filing.header["promoter_address"] = rows[index + 1][-1]
                break
        filing.header["promoter_cin"] = _labelled(company, "CIN No.")
        filing.people.extend(_parse_company_people(company))

    site = _find_table_containing(soup, "Location and Address of the project")
    if site is not None:
        filing.header["project_name"] = _labelled(site, "1. Name of the project")
        filing.header["site_address"] = _labelled(site, "2. Address of the site")
        filing.header["tehsil"] = _labelled(site, "Tehsil")
        filing.header["district"] = _labelled(site, "District")
    if not filing.header.get("project_name"):
        filing.errors.append(
            {
                "stage": "part_a",
                "error_type": "ProjectNameNotFound",
                "message": "Part A carried no project name",
            }
        )


_ROLE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("chairman of the company", "chairman"),
    ("managing director", "managing_director"),
    ("authorised repr", "authorised_representative"),
    ("authorised rep", "authorised_representative"),
    ("director", "director"),
)

_PERSON_FIELD_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Name", "name"),
    ("Residential Address", "address"),
    ("Phone (landline)", "landline"),
    ("Phone (Mobile)", "mobile"),
    ("Email ID", "email"),
    ("PAN No.", "pan"),
)


def _parse_company_people(table: Tag) -> list[dict[str, Any]]:
    """Part A lists the chairman, the MD, each director, and the AR in turn."""
    people: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_row in table.find_all("tr"):
        cells = _cells(raw_row)
        present = _present(cells)
        # A person's photograph sits in its own row, which carries no text.
        photo = raw_row.find("img")
        if photo is not None and photo.get("src") and current is not None:
            current.setdefault("photo_url", _absolute(str(photo["src"])))
        if not present:
            continue
        heading = present[0]
        role = _role_from_heading(heading)
        if role is not None:
            if current and current.get("name"):
                people.append(current)
            current = {"role": role, "name": None, "raw_data": {"heading": heading}}
            continue
        if current is None:
            continue
        for cell in present:
            for prefix, key in _PERSON_FIELD_PATTERNS:
                if cell.startswith(prefix):
                    value = cell[len(prefix) :].lstrip(" :")
                    if value and not current.get(key):
                        current[key] = value
                    break
    if current and current.get("name"):
        people.append(current)
    for person in people:
        person["pan_last4"] = _pan_last4(person.get("pan"))
        person.pop("pan", None)
        phones = [person.pop("landline", None), person.pop("mobile", None)]
        person["phones"] = ", ".join(phone for phone in phones if phone) or None
    return people


def _role_from_heading(heading: str) -> str | None:
    match = re.match(r"^\d+\.\s*(.+?)\s*:?$", heading)
    if not match:
        return None
    label = match.group(1).casefold()
    for needle, role in _ROLE_PATTERNS:
        if needle in label:
            return role
    return None


def _absolute(url: str) -> str:
    if url.startswith("http"):
        return url
    return f"{_PORTAL_BASE}{url if url.startswith('/') else '/' + url}"


def _parse_part_b(soup: BeautifulSoup, filing: RepIFiling) -> None:
    """Project land, license, and the co-licensees who own it."""
    table = _find_table_containing(soup, "Land area of the project")
    if table is None:
        filing.errors.append(
            {
                "stage": "part_b",
                "error_type": "PartBNotFound",
                "message": "Part B (project land and license) was not found",
            }
        )
        return
    filing.profile["licensed_land_acres"] = _decimal(
        _labelled(table, "4. Total licensed area")
    )
    filing.profile["permissible_far"] = _decimal(_labelled(table, "2. Permissible FAR"))
    filing.profile["proposed_far"] = _decimal(
        _labelled(table, "3. FAR proposed to be utilized")
    )
    licence = _labelled(table, "5. License number granted")
    if licence:
        number = re.split(r"\s+valid upto\s+", licence, flags=re.IGNORECASE)[0]
        number = re.sub(r"\s*\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}\s*$", "", number).strip()
        filing.statutory["licence_number"] = number or None
        filing.statutory["licence_date"] = _date(licence)
    for row in _non_empty_rows(table):
        match = re.match(r"^Licensee\s+(\d+)\s*:", row[0])
        if not match:
            continue
        name = None
        address = None
        for cell in row[1:]:
            if cell.startswith("Name"):
                name = cell[len("Name") :].lstrip(" :")
            elif cell.startswith("Address"):
                address = cell[len("Address") :].lstrip(" :")
        if name:
            filing.people.append(
                {
                    "role": "licensee",
                    "name": name,
                    "address": address,
                    "phones": None,
                    "raw_data": {"licensee_index": int(match.group(1))},
                }
            )


def _parse_part_c(soup: BeautifulSoup, filing: RepIFiling) -> None:
    """Estimated cost, total land, and the land-usage split."""
    table = _find_table_containing(soup, "Estimated cost of the project")
    if table is None:
        filing.errors.append(
            {
                "stage": "part_c",
                "error_type": "PartCNotFound",
                "message": "Part C (project details and cost) was not found",
            }
        )
    else:
        filing.cost = {
            "total_cost": _lakhs_to_rupees(_labelled(table, "1. Estimated cost of the project")),
            "land_cost": _lakhs_to_rupees(_labelled(table, "i. Cost of the land")),
            "construction_cost": _lakhs_to_rupees(
                _labelled(table, "ii. Estimated cost of construction")
            ),
            "infrastructure_cost": _lakhs_to_rupees(
                _labelled(table, "iii. Estimated cost of infrastructure")
            ),
            "other_cost": _lakhs_to_rupees(_labelled(table, "iv. Other Costs")),
        }
        total_land = _first_value(table, "2. The total land of the project")
        if total_land:
            filing.profile["land_area_sqm"] = _decimal(total_land)

    usage = _table_by_first_row(
        soup, ("Sr. No.", "Land area under usage", "Area of land (Square Meters)")
    )
    if usage is None:
        filing.errors.append(
            {
                "stage": "part_c_land_usage",
                "error_type": "LandUsageTableNotFound",
                "message": "The land-usage table was not found",
            }
        )
        return
    total_sqm = None
    for row in _non_empty_rows(usage)[1:]:
        # The total row is served with two cells, not three.
        if row[0].casefold().startswith("total"):
            total_sqm = _decimal(row[-1])
            continue
        if len(row) < 3:
            continue
        particular = row[1]
        area_sqm = _decimal(row[2])
        filing.land_usage.append(
            {
                "particular": particular,
                "area_sqm": area_sqm,
                "area_acres": None if area_sqm is None else (area_sqm / _SQM_PER_ACRE).quantize(
                    Decimal("0.0001")
                ),
                "percentage": None,
            }
        )
    if total_sqm and total_sqm > 0:
        for usage_row in filing.land_usage:
            if usage_row["area_sqm"] is not None:
                usage_row["percentage"] = (usage_row["area_sqm"] / total_sqm * 100).quantize(
                    Decimal("0.01")
                )


def _parse_nocs(soup: BeautifulSoup, filing: RepIFiling) -> None:
    table = _table_by_first_row(
        soup,
        (
            "Facility",
            "External/ connecting service to be provided by (Name the agency)",
            "Whether Approval taken from the agency concerned. Yes/No (Annex details in folder C)",
        ),
    )
    if table is None:
        filing.errors.append(
            {
                "stage": "part_c_nocs",
                "error_type": "NocTableNotFound",
                "message": "The external-service NOC table was not found",
            }
        )
        return
    for row in _non_empty_rows(table)[1:]:
        if len(row) < 3:
            continue
        filing.nocs.append(
            {
                "facility": row[0],
                "provider_agency": row[1],
                "approved": row[2].strip().casefold().startswith("y"),
                "approval_reference": None,
            }
        )


def _parse_facilities(soup: BeautifulSoup, filing: RepIFiling) -> None:
    table = None
    for candidate in soup.find_all("table"):
        rows = _non_empty_rows(candidate)
        if rows and len(rows[0]) >= 4 and rows[0][1].startswith("Name of the facility"):
            table = candidate
            break
    if table is None:
        filing.errors.append(
            {
                "stage": "part_c_facilities",
                "error_type": "FacilityTableNotFound",
                "message": "The in-project facility table was not found",
            }
        )
        return
    for row in _non_empty_rows(table)[1:]:
        if len(row) < 3 or not row[0].isdigit():
            continue
        filing.facilities.append(
            {
                "facility": row[1],
                "estimated_cost": _lakhs_to_rupees(row[2]),
                "status": row[3] if len(row) > 3 else None,
            }
        )


def _parse_schedule(soup: BeautifulSoup, filing: RepIFiling) -> None:
    """Likely start and completion dates, plus the apartment-type mix."""
    dates = _find_table_containing(soup, "Likely date of starting the construction work")
    if dates is not None:
        filing.profile["construction_start_date"] = _date(
            _first_value(dates, "i) Likely date of starting")
        )
        filing.profile["proposed_completion_date"] = _date(
            _first_value(dates, "ii) Likely date of completing")
        )
    else:
        filing.errors.append(
            {
                "stage": "part_c_schedule",
                "error_type": "ScheduleTableNotFound",
                "message": "The construction schedule table was not found",
            }
        )

    configs = _table_by_first_row(
        soup, ("Type", "Carpet area(In Square Meter)", "Number of apartments", "Number of towers")
    )
    if configs is None:
        filing.errors.append(
            {
                "stage": "part_c_unit_configs",
                "error_type": "UnitConfigTableNotFound",
                "message": "The apartment-type table was not found",
            }
        )
        return
    total_units = 0
    towers = 0
    for ordinal, row in enumerate(_non_empty_rows(configs)[1:], start=1):
        if len(row) < 4:
            continue
        apartments = _decimal(row[2])
        row_towers = _decimal(row[3])
        if apartments is not None:
            total_units += int(apartments)
        if row_towers is not None:
            towers = max(towers, int(row_towers))
        filing.unit_configs.append(
            {
                "ordinal": ordinal,
                "unit_type": row[0],
                "carpet_area_sqm": _decimal(row[1]),
                "units": int(apartments) if apartments is not None else None,
                "towers": int(row_towers) if row_towers is not None else None,
            }
        )
    filing.profile["total_units"] = total_units or None
    filing.profile["towers"] = towers or None


def _parse_quarterly_expenditure(soup: BeautifulSoup, filing: RepIFiling) -> None:
    """Read the seven-year quarterly tables.

    Only rows carrying all four quarters are kept. The portal renders partial
    years with a single total, and the quarter that total belongs to cannot be
    read off the page, so those rows are counted as unreadable instead of being
    assigned to a quarter.
    """
    category: str | None = None
    unreadable = 0
    for table in soup.find_all("table"):
        rows = _non_empty_rows(table)
        if not rows:
            continue
        flat = " ".join(" ".join(row) for row in rows)
        if "(c) Apartments" in flat:
            category = "apartment"
        elif "(d) Infrastructure" in flat:
            category = "infrastructure"
        header = rows[0]
        if len(header) != 2 or not header[0].startswith("Particulars"):
            continue
        year_match = re.match(r"Year-(\d{4})", header[1])
        if not year_match or category is None:
            continue
        year = int(year_match.group(1))
        for row in rows[1:]:
            if len(row) != 5:
                if len(row) > 1:
                    unreadable += 1
                continue
            parsed = [_decimal(cell) for cell in row[1:]]
            if any(value is None for value in parsed):
                unreadable += 1
                continue
            amounts = [value for value in parsed if value is not None]
            for quarter, amount in enumerate(amounts, start=1):
                filing.expenditure.append(
                    {
                        "category": category,
                        "year": year,
                        "quarter": quarter,
                        "particular": row[0],
                        "amount": amount * _LAKH,
                    }
                )
    if unreadable:
        filing.notes.append(
            {
                "stage": "part_c_expenditure",
                "error_type": "UnreadableQuarterlyRows",
                "message": f"{unreadable} quarterly rows did not carry four quarter columns",
            }
        )


def _parse_part_d(soup: BeautifulSoup, filing: RepIFiling) -> None:
    """The designated collection account."""
    table = _find_table_containing(soup, "Bank Account number")
    if table is None:
        filing.errors.append(
            {
                "stage": "part_d",
                "error_type": "PartDNotFound",
                "message": "Part D (accounts) was not found",
            }
        )
        return
    bank_line = _labelled(table, "Bank and Branch address") or ""
    bank_name, _, branch = bank_line.partition(",")
    filing.bank_account = {
        "bank_name": bank_name.strip() or None,
        "branch_name": branch.strip() or None,
        "account_number": _labelled(table, "Bank Account number"),
        "ifsc": _labelled(table, "IFSC code"),
        "micr": _labelled(table, "MICR code"),
        "branch_code": _labelled(table, "Branch code"),
        "operators": _labelled(table, "4.  Name and address") or _labelled(table, "4. Name and address"),
    }


_PLAN_APPROVAL_MARKER = "Detail of covered area achieved FAR"
# Order matters: "WATER ASSURANCE" is a substring of the storm-water label, and
# the portal spells the storm-water row "STROM".
_UTILITY_MARKERS: tuple[tuple[str, str], ...] = (
    ("STROM WATER ASSURANCE", "storm_water_available"),
    ("STORM WATER ASSURANCE", "storm_water_available"),
    ("WATER ASSURANCE", "water_available"),
    ("SEWERAGE ASSURANCE", "sewerage_available"),
)


def _parse_part_e(soup: BeautifulSoup, filing: RepIFiling) -> None:
    """Plan approvals and the statutory-approval status list."""
    approvals = _find_table_containing(soup, _PLAN_APPROVAL_MARKER)
    plan_approvals: dict[str, bool] = {}
    if approvals is not None:
        for row in _non_empty_rows(approvals):
            # Two cells is a real line; the wider rows are flattened page blobs.
            if len(row) != 2 or row[0].isdigit():
                continue
            label = re.sub(r"^[ivx]+\.\s*", "", row[0]).strip()
            plan_approvals[label] = row[1].strip().casefold().startswith("y")
    else:
        filing.errors.append(
            {
                "stage": "part_e_plan_approvals",
                "error_type": "PlanApprovalTableNotFound",
                "message": "The plan-approval table was not found",
            }
        )
    filing.statutory["plan_approvals"] = plan_approvals or None

    status_table = _table_by_first_row(
        soup, ("Statutory Approvals", "Statutory Approvals Status", "Date")
    )
    if status_table is None:
        filing.errors.append(
            {
                "stage": "part_e_statutory",
                "error_type": "StatutoryApprovalTableNotFound",
                "message": "The statutory-approval status table was not found",
            }
        )
        return
    for row in _non_empty_rows(status_table)[1:]:
        if len(row) < 3:
            continue
        label = row[0].upper()
        obtained = row[1].strip().casefold().startswith("already")
        if "LETTER OF INTENT" in label:
            filing.statutory["loi_date"] = _date(row[2])
            filing.statutory["loi_obtained"] = obtained
        elif "LICENSE" in label:
            filing.statutory["licence_date"] = filing.statutory.get("licence_date") or _date(row[2])
            filing.statutory["licence_obtained"] = obtained
        else:
            for marker, field_name in _UTILITY_MARKERS:
                if marker in label:
                    filing.statutory[field_name] = obtained
                    break


def _parse_part_h(soup: BeautifulSoup, filing: RepIFiling) -> None:
    """Project-wide construction specification lines."""
    table = None
    for candidate in soup.find_all("table"):
        rows = _non_empty_rows(candidate)
        if rows and rows[0][0].startswith("SPECIFICATION OF CONSTRUCTION"):
            table = candidate
            break
    if table is None:
        filing.errors.append(
            {
                "stage": "part_h",
                "error_type": "SpecificationTableNotFound",
                "message": "The construction specification table was not found",
            }
        )
        return
    for row in _non_empty_rows(table)[1:]:
        if len(row) != 3 or not re.fullmatch(r"\d+(?:\.\d+)?", row[0]):
            continue
        filing.specifications.append(
            {
                "scope": "project",
                "unit_type": "all",
                "spec_key": row[1],
                "spec_value": row[2],
            }
        )


def _parse_documents(soup: BeautifulSoup, filing: RepIFiling) -> None:
    """Both document tables: pre-registration and post-registration uploads."""
    tables = _tables_by_first_row(
        soup, ("Sr. No.", "Document Description", "Date of Document Upload", "View Document")
    )
    if not tables:
        filing.errors.append(
            {
                "stage": "documents",
                "error_type": "DocumentTableNotFound",
                "message": "No uploaded-document table was found",
            }
        )
        return
    ordinal = 0
    for table in tables:
        for row in _non_empty_rows(table)[1:]:
            if len(row) < 4 or not row[0].isdigit():
                continue
            ordinal += 1
            link = None
            for anchor in table.find_all("a"):
                if _clean(anchor.get_text(" ", strip=True)).casefold().startswith("view document"):
                    link = anchor.get("href")
                    break
            filing.documents.append(
                {
                    "ordinal": ordinal,
                    "description": row[1],
                    "uploaded_on": _date(row[2]),
                    "view_url": _absolute(str(link)) if link else None,
                }
            )
    if not filing.documents:
        filing.errors.append(
            {
                "stage": "documents",
                "error_type": "NoDocumentsParsed",
                "message": "The document tables produced no rows",
            }
        )


# ---------------------------------------------------------------------------
# Stage derivation
# ---------------------------------------------------------------------------


def derive_stage(
    *,
    register_status: str | None,
    construction_start_date: date | None,
    proposed_completion_date: date | None,
    today: date | None = None,
) -> str | None:
    """Stage from filed dates only.

    ``None`` when the filing does not carry enough dates to place the project.
    Nothing here is inferred from how far along the project looks.
    """
    today = today or datetime.now(UTC).date()
    if (register_status or "").casefold() == "completed":
        return "completed"
    if proposed_completion_date is not None and proposed_completion_date < today:
        # The filed completion date has passed. The register still lists the
        # project as live, so its stage is unknown rather than assumed.
        return None
    if construction_start_date is None:
        return None
    if construction_start_date > today:
        return "pre_launch"
    if proposed_completion_date is None:
        return "under_construction"
    if proposed_completion_date - today <= timedelta(days=_NEAR_POSSESSION_DAYS):
        return "near_possession"
    return "under_construction"


def derive_units_per_acre(
    total_units: int | None, land_area_sqm: Decimal | None
) -> Decimal | None:
    """Density, computed from the project's own land area."""
    if not total_units or not land_area_sqm or land_area_sqm <= 0:
        return None
    acres = land_area_sqm / _SQM_PER_ACRE
    if acres <= 0:
        return None
    return (Decimal(total_units) / acres).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_rep_i(html: str, *, portal_project_id: str) -> RepIFiling:
    """Parse one filing page into its REP-I sections.

    Sections that do not parse are recorded in ``errors``. The caller must not
    write a filing whose ``errors`` list is non-empty.
    """
    soup = BeautifulSoup(html, "html.parser")
    filing = RepIFiling(portal_project_id=str(portal_project_id))
    _parse_header(soup, filing)
    _parse_part_a(soup, filing)
    _parse_part_b(soup, filing)
    _parse_part_c(soup, filing)
    _parse_nocs(soup, filing)
    _parse_facilities(soup, filing)
    _parse_schedule(soup, filing)
    _parse_quarterly_expenditure(soup, filing)
    _parse_part_d(soup, filing)
    _parse_part_e(soup, filing)
    _parse_part_h(soup, filing)
    _parse_documents(soup, filing)

    filing.profile["portal_project_id"] = str(portal_project_id)
    if filing.profile.get("land_area_sqm") is None and filing.header.get("temp_project_id"):
        filing.errors.append(
            {
                "stage": "profile",
                "error_type": "LandAreaNotFound",
                "message": "The filing carried no total land area",
            }
        )
    filing.profile["units_per_acre"] = derive_units_per_acre(
        filing.profile.get("total_units"), filing.profile.get("land_area_sqm")
    )
    return filing


def filing_source_document(html: str, *, portal_project_id: str) -> dict[str, Any]:
    """The ``source_documents`` row for one filing fetch."""
    url = _DETAIL_URL.format(portal_project_id=portal_project_id)
    checked_at = datetime.now(UTC)
    return {
        "authority": _AUTHORITY,
        "title": f"FORM REP-I filing for portal project {portal_project_id}",
        "canonical_url": url,
        "source_record_id": str(portal_project_id),
        "jurisdiction": "Haryana, India",
        "document_type": "regulatory_filing",
        "language": "en",
        "license_name": None,
        "reuse_terms": None,
        "terms_url": None,
        "published_at": None,
        "effective_from": None,
        "effective_to": None,
        "fetched_at": checked_at,
        "checked_at": checked_at,
        "content_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "artifact_reference": None,
    }


class ReraProjectDetailScraper(BaseScraper):
    """Refresh the REP-I filing for projects already in the register."""

    name = "rera_project_detail"
    requires_playwright = True

    async def run(self, run_type: str = "cron", triggered_by: int | None = None) -> dict:
        if not settings.HRERA_DATA_ENABLED:
            return {
                "status": "disabled",
                "run_id": None,
                "reason": "hrera_disabled_by_configuration",
            }
        return await super().run(run_type=run_type, triggered_by=triggered_by)

    async def _work_list(self) -> list[dict[str, Any]]:
        """Projects whose filing is missing or oldest, oldest first.

        Read in its own short-lived session so the network phase below holds no
        database connection.
        """
        from sqlalchemy import select

        from app.core.database import get_bg_session_factory
        from app.models.data_hub import ReraProject, ReraProjectProfile

        session_factory = get_bg_session_factory()
        async with session_factory() as db:
            rows = (
                await db.execute(
                    select(
                        ReraProject.id,
                        ReraProject.rera_number,
                        ReraProject.status,
                        ReraProject.raw_data["portal_project_id"].astext,
                        ReraProjectProfile.id,
                    )
                    .outerjoin(
                        ReraProjectProfile,
                        ReraProjectProfile.rera_project_id == ReraProject.id,
                    )
                    .where(ReraProject.raw_data["portal_project_id"].astext.isnot(None))
                    .order_by(ReraProjectProfile.id.isnot(None), ReraProjectProfile.updated_at)
                    .limit(DEFAULT_BATCH)
                )
            ).all()
        return [
            {
                "rera_project_id": row[0],
                "rera_number": row[1],
                "register_status": row[2],
                "portal_project_id": row[3],
                "has_profile": row[4] is not None,
            }
            for row in rows
        ]

    async def _scrape(self) -> ScrapeResult:
        result = ScrapeResult()
        coverage: dict[str, Any] = {
            "source_url": _PORTAL_BASE,
            "pages_attempted": 0,
            "pages_checked": 0,
            "pages_parsed": 0,
            "records_parsed": 0,
            "status": "failed",
        }
        try:
            work = await self._work_list()
        except Exception as exc:
            logger.warning("Could not read the RERA detail work list: %s", exc)
            result.errors.append(
                {
                    "source_url": _PORTAL_BASE,
                    "stage": "work_list",
                    "error_type": type(exc).__name__,
                    "message": "The detail work list could not be read",
                }
            )
            result.source_coverage.append(coverage)
            return result
        if not work:
            coverage["status"] = "success"
            result.source_coverage.append(coverage)
            return result

        try:
            async with self._playwright_browser() as browser:
                page = await browser.new_page()
                page.set_default_timeout(60000)
                for item in work:
                    portal_id = item.get("portal_project_id")
                    if not portal_id:
                        continue
                    url = _DETAIL_URL.format(portal_project_id=portal_id)
                    coverage["pages_attempted"] += 1
                    try:
                        await page.goto(url, timeout=60000)
                        await asyncio.sleep(1)
                        html = await page.content()
                    except Exception as exc:
                        result.errors.append(
                            {
                                "source_url": url,
                                "stage": "fetch",
                                "error_type": type(exc).__name__,
                                "message": "Filing page fetch failed",
                            }
                        )
                        continue
                    coverage["pages_checked"] += 1
                    filing = parse_rep_i(html, portal_project_id=str(portal_id))
                    if not filing.ok:
                        for error in filing.errors:
                            result.errors.append({"source_url": url, **error})
                        continue
                    record = filing.to_dict()
                    record["rera_project_id"] = item["rera_project_id"]
                    record["rera_number"] = item["rera_number"]
                    record["project_name"] = filing.header.get("project_name")
                    record["register_status"] = item.get("register_status")
                    document = filing_source_document(html, portal_project_id=str(portal_id))
                    document["source_key"] = f"{url}#{document['content_sha256']}"
                    record["_source_key"] = document["source_key"]
                    record["_source_document"] = document
                    result.source_documents.append(document)
                    result.records.append(record)
                    coverage["pages_parsed"] += 1
                    coverage["records_parsed"] += 1
                await page.close()
        except Exception as exc:
            logger.warning("RERA detail Playwright scrape failed: %s", exc)
            result.errors.append(
                {
                    "source_url": _PORTAL_BASE,
                    "stage": "fetch",
                    "error_type": type(exc).__name__,
                    "message": "Browser session failed",
                }
            )

        result.successful_sources = int(coverage["pages_parsed"] > 0)
        coverage["status"] = (
            "failed"
            if coverage["pages_parsed"] == 0
            else "partial"
            if result.errors
            else "success"
        )
        result.source_coverage.append(coverage)
        return result

    async def _upsert(self, db: AsyncSession, records: list[dict[str, Any]]) -> dict:
        """Write one parsed filing.

        Only filings whose parse reported no fatal error reach this method. The
        collection tables are cleared and rewritten inside one transaction, so a
        filing is never left half-updated.
        """
        if not settings.HRERA_DATA_ENABLED:
            return {"found": 0, "upserted": 0, "failed": 0}
        found = len(records)
        upserted = 0
        failed = 0
        for rec in records:
            rec["_upsert_succeeded"] = False
            try:
                source_checked_at = rec.get("_source_checked_at")
                if not isinstance(source_checked_at, datetime):
                    failed += 1
                    continue
                async with db.begin_nested():
                    await self._write_filing(db, rec, source_checked_at)
                upserted += 1
                rec["_upsert_succeeded"] = True
            except Exception as exc:
                logger.warning(
                    "Failed to write REP-I filing for project %s: %s",
                    rec.get("rera_number"),
                    exc,
                )
                failed += 1
        return {"found": found, "upserted": upserted, "failed": failed}

    async def _write_filing(
        self, db: AsyncSession, rec: dict[str, Any], checked_at: datetime
    ) -> None:
        from sqlalchemy import delete, update

        from app.models.data_hub import (
            ReraLandUsage,
            ReraProject,
            ReraProjectBankAccount,
            ReraProjectCost,
            ReraProjectDocument,
            ReraProjectFacility,
            ReraProjectNoc,
            ReraProjectPerson,
            ReraProjectProfile,
            ReraProjectSpecification,
            ReraProjectUnitConfig,
            ReraQuarterlyExpenditure,
            ReraStatutoryApproval,
        )
        from app.services.data_hub.provenance import get_or_create_source_document

        project_id = rec["rera_project_id"]
        document_id = await get_or_create_source_document(
            db, {k: v for k, v in rec["_source_document"].items() if k != "source_key"}
        )

        # Collections are positional and can shrink, so they are replaced whole.
        for model in (
            ReraLandUsage,
            ReraQuarterlyExpenditure,
            ReraProjectDocument,
            ReraProjectFacility,
            ReraProjectNoc,
            ReraProjectUnitConfig,
            ReraProjectSpecification,
            ReraProjectPerson,
        ):
            await db.execute(delete(model).where(model.rera_project_id == project_id))

        profile = dict(rec["profile"])
        profile["stage"] = derive_stage(
            register_status=rec.get("register_status"),
            construction_start_date=profile.get("construction_start_date"),
            proposed_completion_date=profile.get("proposed_completion_date"),
        )
        # Rows written before the slug column existed get theirs on this pass.
        slug = project_slug(rec.get("project_name"), rec.get("rera_number"))
        if slug:
            await db.execute(
                update(ReraProject)
                .where(ReraProject.id == project_id, ReraProject.slug.is_(None))
                .values(slug=slug)
            )
        await self._upsert_one(
            db,
            ReraProjectProfile,
            "rera_project_id",
            project_id,
            profile,
            document_id,
            checked_at,
            touch=True,
        )
        await self._upsert_one(
            db, ReraProjectCost, "rera_project_id", project_id, rec["cost"], document_id, checked_at
        )
        await self._upsert_one(
            db,
            ReraStatutoryApproval,
            "rera_project_id",
            project_id,
            rec["statutory"],
            document_id,
            checked_at,
        )
        await self._upsert_one(
            db,
            ReraProjectBankAccount,
            "rera_project_id",
            project_id,
            rec["bank_account"],
            document_id,
            checked_at,
        )

        for model, rows in (
            (ReraLandUsage, rec["land_usage"]),
            (ReraQuarterlyExpenditure, rec["expenditure"]),
            (ReraProjectDocument, rec["documents"]),
            (ReraProjectFacility, rec["facilities"]),
            (ReraProjectNoc, rec["nocs"]),
            (ReraProjectPerson, rec["people"]),
            (ReraProjectUnitConfig, rec["unit_configs"]),
            (ReraProjectSpecification, rec["specifications"]),
        ):
            for row in rows:
                values = {
                    key: value
                    for key, value in row.items()
                    if hasattr(model, key)
                }
                db.add(
                    model(
                        rera_project_id=project_id,
                        source_document_id=document_id,
                        **values,
                    )
                )
