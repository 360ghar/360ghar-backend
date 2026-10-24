"""RERA project scraper — Delhi RERA register and project filing pages.

The host is not ``rera.delhi.gov.in``
-------------------------------------
``rera.delhi.gov.in`` (164.100.77.33) accepts no TCP connection on port 80 or 443
from this environment: both time out, so every request to it fails before a byte
is parsed. The Delhi RERA application that actually serves the register is
``https://erera.co.in``, built by C-DAC Mohali. Its footer reads ``© RERA Delhi``,
it links ``helpdesk@rera.delhi.gov.in``, and it serves live ``DLRERA2026P…``
registrations. That host is what this scraper reads. A future reader who finds
``rera.delhi.gov.in`` dead should not conclude Delhi RERA has no machine-readable
register — it does, and it is here.

What is open, and what is not
-----------------------------
* **The register is open.**
  ``GET /reradelhiindex/PublicView/RegisteredProjectDetail`` returns one
  server-rendered document carrying every registered Delhi project in
  ``table#dataTableSearchProject``. No CAPTCHA, no session cookie, no
  JavaScript-built table, and no server-side pagination: DataTables paginates
  what the server already sent, so one fetch is the whole register.
* **A project's filing is open.**
  ``GET /reradelhiindex/PublicView/ProjectViewDetails?inProject_ID=&inPromoter_ID=&inPromoterType=``
  returns the filed project detail — address, land area, tower inventory,
  promoter, documents, approvals — with no CAPTCHA. All three parameters come
  from the register row, so the filing needs no search round trip.
* **The search is CAPTCHA-gated.** ``POST /reradelhiindex/PublicView/ProjectPVregdprojectInfo``
  answers a blank captcha with HTTP 200 and a ~5 KB script partial instead of
  rows, and the search page at ``/reradelhiindex/PublicView/ProjectInfo`` renders
  ``CaptchaText`` fields. This scraper never posts to either, and does not try to
  solve one. It records the blocker as ``DELHI_SEARCH_REQUIRES_CAPTCHA`` in the
  module rather than in a run, because the register already carries every
  registered project: there is nothing the search would add. The name is kept so
  the next reader recognises the wall instead of rediscovering it.

No browser is needed
--------------------
Both pages are fully server-rendered, so ``requires_playwright`` is False and
both fetches go through ``BaseScraper._fetch_url`` (httpx with tenacity retry).
This is the opposite of the HRERA surface, where the filing page needs a browser
and the listing page cannot be reached at all.

District: the row's own, never a guess
--------------------------------------
The district comes from the row's own District Name cell. A blank or unreadable
cell falls back to the **state** (``Delhi``), never to a district. The register
names eleven distinct districts, not ten — ``Shahdara`` is a Delhi district in its
own right and three rows file against it. That fallback rule matters more than it
looks: ``micro_market.py`` and ``market_pulse.py`` both use the district as the
city, so a fabricated district does not mislabel one project, it inflates one
city's project count and removes the project from its real city's. The same rule
is applied by ``rera_portal_scan.py`` (``Haryana``) and ``uprera_projects.py``
(``Uttar Pradesh``).

Identifiers: why ``portal_project_id`` is not written
----------------------------------------------------
``rera_projects`` carries a unique partial index on the SQL expression
``(raw_data ->> 'portal_project_id')``. HRERA's portal project ids are small
integers (``2779``); Delhi's are larger integers in the **same namespace**
(``10143``). Writing Delhi's id into that key would let an HRERA id-range walk
reach the same number and collide with the Delhi row, overwriting a Delhi
project with Haryana data. Delhi therefore writes ``raw_data.delhi_project_id``
and ``raw_data.portal = "delhi_rera"`` and never writes ``portal_project_id``, so
the HRERA index expression is NULL on every Delhi row and the index cannot
constrain — or be matched by — a Delhi row. Idempotency for Delhi rests on the
plain unique constraint on ``rera_number``, which is how ``uprera_projects.py``
does it. ``tests/integration/services/test_delhi_rera_write.py`` stores a Delhi
project and an HRERA project under the same numeric id and asserts both survive.

The registration number is real
-------------------------------
Unlike the HRERA filing page, which states only a pre-registration temp id, the
Delhi register states the assigned registration number (``DLRERA2026P0005``) in
its own column, and it is unique per row. It is used as ``rera_number`` verbatim.
The register publishes no registration *date*, so ``registration_date`` stays
null: the year inside the number is a year, and turning it into a date would mean
inventing a day and a month.

Failing loudly
--------------
The register is read whole or not at all. ``parse_registered_projects_html``
returns records only when every row in the table parsed and the document is
complete; if a single row cannot yield its identity fields, or the document was
cut off mid-stream, it returns **no** records and an error naming the row or the
missing marker. A partial register is worse than no register, because the write
path cannot tell the two apart — that is how a 3822-row grid once shipped as a
2315-row success.

The two copies of the register are used as the completeness check. The document
renders the same projects twice: once in ``#dataTableSearchProject`` (the
register tab) and once in ``#dataTableSearchQUpdatesProject`` (the quarterly
updates tab), and a truncated response loses the tail. If the second copy carries
rows and its registration numbers do not match the first copy's, the document is
not what the portal sent and nothing is written.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.data_hub import ReraProject
from app.services.data_hub.base_scraper import BaseScraper, ScrapeResult
from app.services.data_hub.rera_project_detail import project_slug
from app.services.data_hub.utils import generate_slug

logger = logging.getLogger(__name__)

_PORTAL_BASE = "https://erera.co.in"
_REGISTER_URL = f"{_PORTAL_BASE}/reradelhiindex/PublicView/RegisteredProjectDetail"
_DETAIL_URL = f"{_PORTAL_BASE}/reradelhiindex/PublicView/ProjectViewDetails"
_SEARCH_URL = f"{_PORTAL_BASE}/reradelhiindex/PublicView/ProjectInfo"
# The search's data endpoint, recorded only so the blocker below names it.
_SEARCH_DATA_URL = f"{_PORTAL_BASE}/reradelhiindex/PublicView/ProjectPVregdprojectInfo"

_AUTHORITY = "Real Estate Regulatory Authority, NCT of Delhi"
_JURISDICTION = "NCT of Delhi, India"
_PORTAL_MARKER = "delhi_rera"
_REGISTERED_STATUS = "registered"

# The fallback for a row whose District Name cell is blank or unreadable: the
# state, never a district the row does not name. Delhi registers only NCT of
# Delhi projects, so the state is a fact of the register while "New Delhi" would
# be a guess. See the module docstring for why this is not cosmetic.
_DEFAULT_DISTRICT = "Delhi"

# The register's own table, and the second table the same document renders the
# same projects into for the quarterly-updates tab. Both are read: the first
# produces the records, the second proves the first was not truncated.
_REGISTER_TABLE_ID = "dataTableSearchProject"
_MIRROR_TABLE_ID = "dataTableSearchQUpdatesProject"
# A complete register document ends here. A response cut off mid-stream does not,
# and the missing marker is the signal that the rows above it are not the whole
# register.
_DOCUMENT_END_MARKER = "</html>"

# Recorded so the next reader does not rediscover the wall. Not raised at run
# time: the register is open and carries every registered project.
DELHI_SEARCH_REQUIRES_CAPTCHA = "DELHI_SEARCH_REQUIRES_CAPTCHA"

# Column positions inside a register row, in the order the table renders them:
# SNo, District Name, Project's Name, Promoter's Name, Registration Number,
# Registration Valid Upto Date, Type of Project, View Details. The project-name
# and registration cells also carry classes, which are preferred over position.
_COL_DISTRICT = 1
_COL_PROMOTER = 3
_COL_VALID_UPTO = 5
_COL_PROJECT_TYPE = 6

# A row that cannot fill these is a dropped row, and a dropped row fails the run.
_ROW_REQUIRED_CELLS = 8

# Seconds between filing fetches. The portal is a public service; this is a
# courtesy pace, not a technical limit. The register itself is one fetch.
_DETAIL_DELAY_SECONDS = 0.5
_FETCH_TIMEOUT_SECONDS = 120.0

# The register states its dates as ``18-Feb-2031``. The numeric form is accepted
# too, because a portal that renders a date for a human may render either.
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_NAMED_DATE_RE = re.compile(r"^(\d{1,2})[-/ ]([A-Za-z]{3,9})[-/ ](\d{2,4})$")
_NUMERIC_DATE_RE = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$")
# The register annotates a promoter with its own filing type, e.g.
# ``NBCC (India) Limited (Other than Individual)``. The same promoter files as an
# individual on one project and an organisation on another, so leaving the
# annotation inside the name would split one developer into two slugs on the
# developer pages. The hidden ``PromoterType`` input carries the same fact as a
# code, and it is recorded in ``raw_data``.
_PROMOTER_LABEL_RE = re.compile(r"\s*\(\s*(?:other\s+than\s+)?individual\s*\)\s*$", re.IGNORECASE)
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

_SECTION_ABOUT = "About the Project"
_SECTION_PROMOTER = "Promoter Details"
_SECTION_LAND = "Project Land Details"
_SECTION_INVENTORY = "Project Building/ Tower/ Block Construction & Inventory Details"
_SECTION_MEMBERS = "Organization Member Details (If Applicable)"
_SECTION_DOCUMENTS = "Project Documents"
_SECTION_APPROVALS = "Project Approvals Document(s)"


def _clean(value: object) -> str:
    """Collapse the register's generous whitespace into one line.

    Takes whatever BeautifulSoup hands back. An attribute is typed
    ``str | AttributeValueList | None`` even for the single-valued attributes this
    parser reads, so the value is coerced rather than assumed to be a string.
    """
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _collapse_address(value: str | None) -> str | None:
    """One readable line from an address the page renders across ``<br/>`` tags.

    ``Bharat Business Park , Ring Road Dwarka , South West Delhi , Delhi - 110023``
    becomes ``Bharat Business Park, Ring Road Dwarka, South West Delhi, Delhi -
    110023``. The comma shape is kept because ``micro_market.derive_locality``
    splits the address on commas to find the locality, so an address whose parts
    are run together loses its locality.

    Two template artifacts are dropped. The page renders each part as
    ``<label>:&#160;<value>`` and emits the separator even when the label is
    empty, so one filing's address begins ``:&#160;DELHI MUNICIPAL PRESS...``;
    the leading colon and the space after it are the separator, not the address.
    An empty part also leaves its comma behind, which is how ``SECTOR-10, ,
    DWARKA`` appears, so consecutive commas collapse to one. Both are the portal's
    rendering, not a value the register stated, and neither changes which parts
    the address has.
    """
    text = _clean(value)
    if not text:
        return None
    text = re.sub(r"^[:\-]\s*", "", text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r",\s*", ", ", text)
    text = re.sub(r"(?:,\s*)+,", ",", text)
    text = re.sub(r"\s+-\s+", " - ", text)
    return text.strip(" ,") or None


def _parse_date(value: str | None) -> date | None:
    """Read ``18-Feb-2031`` or ``18-02-2031``. ``None`` when neither fits."""
    text = _clean(value)
    if not text:
        return None
    named = _NAMED_DATE_RE.match(text)
    if named is not None:
        day_text, month_text, year_text = named.groups()
        month = _MONTHS.get(month_text[:3].lower())
        if month is None:
            return None
        return _safe_date(int(year_text), month, int(day_text))
    numeric = _NUMERIC_DATE_RE.match(text)
    if numeric is not None:
        day_text, month_text, year_text = numeric.groups()
        return _safe_date(int(year_text), int(month_text), int(day_text))
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _decimal(value: str | None) -> Decimal | None:
    """The first number in a cell that appends its own unit, e.g. ``57184.17 (in sqr mtrs)``."""
    text = _clean(value)
    match = _NUMBER_RE.search(text.replace(",", ""))
    if match is None:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def _int(value: str | None) -> int | None:
    number = _decimal(value)
    if number is None:
        return None
    return int(number)


def _normalize_url(href: str) -> str:
    """Turn the register's backslash-separated certificate path into a URL.

    The portal writes ``.../readwritePRJCert\\10143\\/PRJcert_….pdf``. A browser
    normalises the backslashes to slashes, and the normalised form was verified to
    answer HTTP 200 with ``application/pdf``; the verbatim attribute is kept in
    ``raw_data`` beside it.
    """
    return href.replace("\\", "/")


def _promoter_name(raw: str | None) -> str | None:
    """The promoter's name with the register's filing-type annotation removed."""
    text = _clean(raw)
    if not text:
        return None
    stripped = _PROMOTER_LABEL_RE.sub("", text).strip()
    return stripped or None


def _detail_url(project_id: str, promoter_id: str, promoter_type: str) -> str:
    """The filing URL for one register row. All three parts come from the row."""
    return (
        f"{_DETAIL_URL}?inProject_ID={quote(project_id)}"
        f"&inPromoter_ID={quote(promoter_id)}"
        f"&inPromoterType={quote(promoter_type)}"
    )


def _hidden(row: Any, class_name: str) -> str | None:
    """The value of one of the row's hidden identity inputs."""
    element = row.select_one(f"input.{class_name}")
    if element is None:
        return None
    value = _clean(element.get("value"))
    return value or None


@dataclass(frozen=True)
class RegisterParse:
    """One register read: the records, and why there are none when there are none."""

    records: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)


def _register_cells(row: Any) -> list[str]:
    return [_clean(cell.get_text(" ", strip=True)) for cell in row.find_all("td", recursive=False)]


def _row_record(
    row: Any, *, ordinal: int
) -> tuple[dict[str, Any] | None, list[str]]:
    """One register row as a record, or the reasons it is not one.

    The second element is the human-readable reason each missing field was
    refused; the caller turns each into an error entry, so it is a list of
    sentences rather than of records.

    Nothing is inferred: a row that cannot state its district, its name, its
    registration number and the identity triple that addresses its filing is
    refused rather than written with a placeholder.
    """
    cells = _register_cells(row)
    problems: list[str] = []
    if len(cells) < _ROW_REQUIRED_CELLS:
        return None, [
            f"row {ordinal} rendered {len(cells)} cells, expected {_ROW_REQUIRED_CELLS}"
        ]

    district_cell = cells[_COL_DISTRICT]
    # The portal publishes eleven Delhi districts. A cell that names nothing is
    # left to the state fallback below rather than being filled with a district.
    district = district_cell or _DEFAULT_DISTRICT

    name_cell = row.select_one("td.project-name")
    registration_cell = row.select_one("td.project-diary-number")
    if name_cell is None:
        problems.append("no td.project-name cell")
    if registration_cell is None:
        problems.append("no td.project-diary-number cell")

    project_name = _clean(name_cell.get("data-project-name")) if name_cell else ""
    if not project_name and name_cell is not None:
        project_name = _clean(name_cell.get_text(" ", strip=True))
    if not project_name:
        problems.append("no project name")

    registration_number = _clean(registration_cell.get("data-diary-no")) if registration_cell else ""
    if not registration_number and registration_cell is not None:
        registration_number = _clean(registration_cell.get_text(" ", strip=True))
    if not registration_number:
        problems.append("no registration number")

    project_id = _hidden(row, "hdnProjectID")
    promoter_id = _hidden(row, "hdnPromoterID")
    promoter_type = _hidden(row, "hdnPromoterType")
    # The inputs are declared numeric by the page's own validation attributes. A
    # non-numeric value would be a markup change, and it would also be unsafe to
    # place in the filing URL unquoted, so it is refused instead of encoded.
    for label, value in (
        ("hdnProjectID", project_id),
        ("hdnPromoterID", promoter_id),
        ("hdnPromoterType", promoter_type),
    ):
        if value is None:
            problems.append(f"no input.{label}")
        elif not value.isdigit():
            problems.append(f"input.{label} is not numeric")

    if problems:
        return None, [f"row {ordinal}: {problem}" for problem in problems]

    assert project_id is not None and promoter_id is not None and promoter_type is not None

    promoter_raw = cells[_COL_PROMOTER] or None
    promoter = _promoter_name(promoter_raw)
    certificate = row.select_one('a[title="View Certificate"]')
    certificate_href = _clean(certificate.get("href")) if certificate is not None else ""

    valid_upto_raw = cells[_COL_VALID_UPTO]
    project_type_raw = cells[_COL_PROJECT_TYPE] or None
    filing_url = _detail_url(project_id, promoter_id, promoter_type)

    record: dict[str, Any] = {
        "rera_number": registration_number,
        "project_name": project_name,
        "developer_name": promoter,
        # The developer pages group projects by this slug and
        # ``developer_dossier.developer_slug`` derives it the same way from the
        # same name, so the two agree. Without it a developer page shows a score
        # but no projects.
        "developer_slug": generate_slug(promoter) if promoter else None,
        # The registration number is unique, so appending it makes the public URL
        # key unique by construction.
        "slug": project_slug(project_name, registration_number),
        "district": district,
        "expiry_date": _parse_date(valid_upto_raw),
        "project_type": project_type_raw,
        # The register is titled "Registered Project Detail" and lists
        # registrations in force; a project removed from it is simply absent from
        # the next read rather than marked.
        "status": _REGISTERED_STATUS,
        # The filing is the per-project citation a reader can open, so it is the
        # source URL; the register is recorded as the run's source document.
        "source_url": filing_url,
        "raw_data": {
            "portal": _PORTAL_MARKER,
            # Deliberately not ``portal_project_id``: see the module docstring.
            "delhi_project_id": project_id,
            "promoter_id": promoter_id,
            "promoter_type": promoter_type,
            "promoter_name_raw": promoter_raw,
            "registration_valid_upto": valid_upto_raw or None,
            "certificate_url": _normalize_url(certificate_href) if certificate_href else None,
            "certificate_href_raw": certificate_href or None,
            "register_url": _REGISTER_URL,
            "register_row": ordinal,
            "detail_url": filing_url,
            "register_cells": cells,
        },
    }
    return record, []


def _mirror_registration_numbers(soup: BeautifulSoup) -> list[str]:
    """The registration numbers the document's second copy of the register holds."""
    table = soup.find("table", id=_MIRROR_TABLE_ID)
    if table is None:
        return []
    body = table.find("tbody")
    if body is None:
        return []
    numbers: list[str] = []
    for row in body.find_all("tr", recursive=False):
        cell = row.select_one("td.project-diary-number")
        if cell is None:
            continue
        value = _clean(cell.get("data-diary-no")) or _clean(cell.get_text(" ", strip=True))
        if value:
            numbers.append(value)
    return numbers


def parse_registered_projects_html(html: str) -> RegisterParse:
    """Every registered Delhi project the register document carries.

    Returns records only when the whole register parsed: a missing table, a
    missing document end, a row that cannot state its identity, or a second copy
    of the register that disagrees with the first all return no records and the
    reason. The caller must not write a partial register, and cannot tell a
    partial one from a complete one by looking at the records alone.
    """
    soup = BeautifulSoup(html, "html.parser")
    coverage: dict[str, Any] = {
        "register_rows": 0,
        "mirror_rows": 0,
        "records_parsed": 0,
        "rows_refused": 0,
    }
    table = soup.find("table", id=_REGISTER_TABLE_ID)
    if table is None:
        return RegisterParse(
            errors=[
                {
                    "stage": "parse",
                    "error_type": "ExpectedRegisterTableNotFound",
                    "message": (
                        f"Delhi RERA register document carried no table#{_REGISTER_TABLE_ID}; "
                        "the register markup changed or the page was not the register"
                    ),
                }
            ],
            coverage=coverage,
        )
    body = table.find("tbody")
    rows = body.find_all("tr", recursive=False) if body is not None else []
    coverage["register_rows"] = len(rows)
    if not rows:
        return RegisterParse(
            errors=[
                {
                    "stage": "parse",
                    "error_type": "EmptyRegisterTable",
                    "message": (
                        f"table#{_REGISTER_TABLE_ID} rendered no rows; a register with no "
                        "projects is not a register read"
                    ),
                }
            ],
            coverage=coverage,
        )

    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for ordinal, row in enumerate(rows, start=1):
        record, problems = _row_record(row, ordinal=ordinal)
        if record is None:
            errors.extend({"stage": "parse", "error_type": "RegisterRowNotParsed", "message": m}
                          for m in problems)
            continue
        records.append(record)
    coverage["rows_refused"] = len(rows) - len(records)

    if not errors and _DOCUMENT_END_MARKER not in html:
        errors.append(
            {
                "stage": "parse",
                "error_type": "RegisterDocumentTruncated",
                "message": (
                    f"register document did not end with {_DOCUMENT_END_MARKER}; the response "
                    "was cut off, so the rows above are not the whole register"
                ),
            }
        )

    mirror_numbers = _mirror_registration_numbers(soup)
    coverage["mirror_rows"] = len(mirror_numbers)
    register_numbers = [record["rera_number"] for record in records]
    if not errors and mirror_numbers and set(mirror_numbers) != set(register_numbers):
        errors.append(
            {
                "stage": "parse",
                "error_type": "RegisterCopiesDisagree",
                "message": (
                    "the document's second copy of the register "
                    f"(table#{_MIRROR_TABLE_ID}) carries {len(mirror_numbers)} registration "
                    f"numbers against {len(register_numbers)} in table#{_REGISTER_TABLE_ID}, "
                    "so the document is not what the portal sent"
                ),
            }
        )

    if errors:
        # No records on any integrity failure: the write path cannot tell a
        # partial register from a complete one, and neither can a reader.
        coverage["records_parsed"] = 0
        return RegisterParse(records=[], errors=errors, coverage=coverage)

    coverage["records_parsed"] = len(records)
    return RegisterParse(records=records, errors=[], coverage=coverage)


def _label_value_pairs(table: Any | None) -> dict[str, str]:
    """Read a two- or four-cell label/value table into a dict.

    The filing renders most of its facts as ``<td>Label</td><td>Value</td>``, and
    the wider rows as label/value/label/value. Values are kept verbatim; nothing
    is parsed into a number here, because the same table carries labels whose
    values are prose. A section the page does not carry yields an empty dict.
    """
    pairs: dict[str, str] = {}
    if table is None:
        return pairs
    for row in table.find_all("tr"):
        cells = [_clean(cell.get_text(" ", strip=True)) for cell in row.find_all("td")]
        for index in range(0, len(cells) - 1, 2):
            label = cells[index].rstrip(":").strip()
            if not label:
                continue
            pairs[label] = cells[index + 1]
    return pairs


def _section_table(soup: BeautifulSoup, title: str) -> Any | None:
    """The table that follows a section heading, or ``None`` when it is absent.

    Matched on a heading prefix, because the filing varies the heading's tail
    with the filing: the promoter section is ``Promoter Details (Other Than
    Individual)`` on a company filing and ``Promoter Details (Individual)`` on an
    individual's. An exact match would silently read the second as absent.
    """
    for heading in soup.find_all(class_=re.compile("view-detail-heading")):
        if _clean(heading.get_text(" ", strip=True)).startswith(title):
            return heading.find_next("table")
    return None


def _section_rows(table: Any | None) -> list[Any]:
    """The body rows of a section table, headers excluded."""
    if table is None:
        return []
    body = table.find("tbody")
    if body is None:
        return []
    rows = body.find_all("tr", recursive=False)
    # A section with no records renders a single row of ``--`` placeholders.
    if len(rows) == 1 and all(
        _clean(cell.get_text(" ", strip=True)) in ("", "--") for cell in rows[0].find_all("td")
    ):
        return []
    return list(rows)


def _inventory_units(table: Any | None) -> tuple[int | None, int | None, bool]:
    """Total filed units and tower count from the construction/inventory section.

    The section renders one row per tower, each followed by a row holding the
    tower's unit-type table. Both the tower rows and the nested unit tables are
    counted from the section table itself, so a flat rendering (no nesting) is
    read the same way as a nested one: the unit tables are whatever unit-type
    tables the section contains.

    ``total_units`` is the sum of the ``Total Number of Apartment/ Shop/ Plot``
    column, located by its header rather than by position, because the column
    order is not guaranteed across project types. ``None`` is returned when no
    unit table or no such column was found, and also when the column is present
    but not one cell under it could be read: an unreadable inventory is not the
    same fact as a project with no units.

    That second case is not hypothetical. Eight of the 133 Delhi filings render
    the column header and then no data rows at all, so a header match alone would
    report ``0`` units for a project whose filing states nothing. A ``0`` the
    filing itself states is kept, because that is the register's answer; a ``0``
    produced by adding up nothing is ours, and must not be published.
    """
    if table is None:
        return None, None, False
    unit_tables = table.find_all("table")
    if not unit_tables:
        unit_tables = [table]
    towers = sum(
        1
        for row in _section_rows(table)
        if len(row.find_all("td", recursive=False)) >= 3 and not row.find("table")
    )
    total = 0
    found_column = False
    read_any = False
    for unit_table in unit_tables:
        header_cells = [
            _clean(cell.get_text(" ", strip=True)).lower()
            for cell in unit_table.find_all("tr")[0].find_all(["td", "th"])
        ] if unit_table.find_all("tr") else []
        column = next(
            (index for index, text in enumerate(header_cells) if "total number" in text),
            None,
        )
        if column is None:
            continue
        found_column = True
        for row in unit_table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if column >= len(cells):
                continue
            units = _int(cells[column].get_text(" ", strip=True))
            if units is not None:
                total += units
                read_any = True
    if not found_column or not read_any:
        return None, towers or None, False
    return total, towers or None, True


@dataclass(frozen=True)
class ProjectDetail:
    """What one filing page states, with every field optional.

    A missing fact stays ``None``. The filing is not required to carry all of
    them — a project registered before a field existed simply has no row for it —
    so absence is reported, not filled.
    """

    project_name: str | None = None
    address: str | None = None
    amenities: str | None = None
    zone: str | None = None
    project_type: str | None = None
    project_status: str | None = None
    project_cost_inr: Decimal | None = None
    start_date: date | None = None
    proposed_completion_date: date | None = None
    web_link: str | None = None
    mega_project: str | None = None
    promoter_name: str | None = None
    promoter_registered_address: str | None = None
    promoter_official_address: str | None = None
    land_area_sqm: Decimal | None = None
    towers: int | None = None
    units_total: int | None = None
    inventory_parsed: bool = False
    member_count: int | None = None
    document_count: int | None = None
    approval_count: int | None = None
    errors: tuple[dict[str, str], ...] = ()


def parse_project_detail_html(html: str) -> ProjectDetail:
    """Read one Delhi RERA filing page.

    The page renders every section as a heading followed by a table, so each fact
    is located by its own section heading and its own row label rather than by
    position. A section the page does not carry yields ``None`` fields, which is
    the honest answer: this filing does not state it.

    Nothing here is required, so an unreadable page returns ``None`` fields and an
    error rather than empty facts presented as facts. The register row already
    holds the project's identity; this page only adds to it.
    """
    soup = BeautifulSoup(html, "html.parser")
    errors: list[dict[str, str]] = []

    about = _label_value_pairs(_section_table(soup, _SECTION_ABOUT))
    promoter = _label_value_pairs(_section_table(soup, _SECTION_PROMOTER))
    land = _label_value_pairs(_section_table(soup, _SECTION_LAND))

    if not about:
        errors.append(
            {
                "stage": "parse",
                "error_type": "DetailSectionNotFound",
                "message": (
                    f"filing page carried no readable '{_SECTION_ABOUT}' section; the filing "
                    "markup changed or the page was not a filing"
                ),
            }
        )

    cost = next(
        (value for label, value in about.items() if label.lower().startswith("project cost")),
        None,
    )
    start = next(
        (value for label, value in about.items() if label.lower() == "project start date"),
        None,
    )
    completion = next(
        (value for label, value in about.items() if "completion" in label.lower()),
        None,
    )
    units_total, towers, inventory_parsed = _inventory_units(
        _section_table(soup, _SECTION_INVENTORY)
    )

    return ProjectDetail(
        project_name=about.get("Project Name") or None,
        address=_collapse_address(about.get("Project Address")),
        amenities=about.get("Project Amenities") or None,
        # The Delhi instance of the C-DAC application inherited the Punjab
        # template: this row serves Punjab zone text such as "Zone 3 - Ludhiana"
        # on Delhi filings. It is recorded verbatim and never used to place a
        # project, because a zone label naming Ludhiana says nothing about Delhi.
        zone=about.get("Project Zone") or None,
        project_type=about.get("Type of Project") or None,
        project_status=about.get("Project Status") or None,
        project_cost_inr=_decimal(cost),
        start_date=_parse_date(start),
        proposed_completion_date=_parse_date(completion),
        web_link=about.get("Project Web Link") or None,
        mega_project=about.get("Mega Project (Yes/No)") or None,
        # A company filing labels this row ``Name of Organization`` and an
        # individual's labels it ``Name``. Contact details in the same table —
        # phone, email, and the project's authorized person — are deliberately not
        # read: they are personal data the register publishes for a different
        # purpose, and nothing on this platform needs them.
        promoter_name=promoter.get("Name of Organization") or promoter.get("Name") or None,
        promoter_registered_address=_collapse_address(
            promoter.get("Registered Address of Organization")
        ),
        promoter_official_address=_collapse_address(promoter.get("Official Address")),
        land_area_sqm=_decimal(
            next(
                (
                    value
                    for label, value in land.items()
                    if label.lower().startswith("total area of land proposed")
                ),
                None,
            )
        ),
        towers=towers,
        units_total=units_total,
        inventory_parsed=inventory_parsed,
        member_count=len(_section_rows(_section_table(soup, _SECTION_MEMBERS))),
        document_count=len(_section_rows(_section_table(soup, _SECTION_DOCUMENTS))),
        approval_count=len(_section_rows(_section_table(soup, _SECTION_APPROVALS))),
        errors=tuple(errors),
    )


def _register_source_document(html: str, *, checked_at: datetime) -> dict[str, Any]:
    """The ``source_documents`` row for one register fetch."""
    return {
        "source_key": f"{_REGISTER_URL}#{hashlib.sha256(html.encode('utf-8')).hexdigest()}",
        "authority": _AUTHORITY,
        "title": "Delhi RERA registered project register",
        "canonical_url": _REGISTER_URL,
        "source_record_id": None,
        "jurisdiction": _JURISDICTION,
        "document_type": "registry_page",
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


def _detail_source_document(
    html: str, *, url: str, project_id: str, checked_at: datetime
) -> dict[str, Any]:
    """The ``source_documents`` row for one filing fetch."""
    return {
        "source_key": f"{url}#{hashlib.sha256(html.encode('utf-8')).hexdigest()}",
        "authority": _AUTHORITY,
        "title": f"Delhi RERA project filing for portal project {project_id}",
        "canonical_url": url,
        "source_record_id": project_id,
        "jurisdiction": _JURISDICTION,
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


def _apply_detail(record: dict[str, Any], detail: ProjectDetail) -> None:
    """Fold one filing read into the register record it belongs to.

    The register stays the authority for everything it states. The filing adds
    only what the register does not carry — the filed address, the land area, the
    unit count, the declared completion date — and its own copy of the facts is
    kept under ``raw_data.detail`` rather than overwriting the register's, so a
    reader can see both spellings of the same project.
    """
    raw = record.setdefault("raw_data", {})
    raw["detail"] = {
        "project_name": detail.project_name,
        "amenities": detail.amenities,
        "zone": detail.zone,
        "project_type": detail.project_type,
        "project_status": detail.project_status,
        "project_cost_inr": str(detail.project_cost_inr)
        if detail.project_cost_inr is not None
        else None,
        "start_date": detail.start_date.isoformat() if detail.start_date else None,
        "proposed_completion_date": detail.proposed_completion_date.isoformat()
        if detail.proposed_completion_date
        else None,
        "web_link": detail.web_link,
        "mega_project": detail.mega_project,
        "promoter_name": detail.promoter_name,
        "promoter_registered_address": detail.promoter_registered_address,
        "promoter_official_address": detail.promoter_official_address,
        "towers": detail.towers,
        "units_total": detail.units_total,
        "inventory_parsed": detail.inventory_parsed,
        "member_count": detail.member_count,
        "document_count": detail.document_count,
        "approval_count": detail.approval_count,
    }
    if detail.address:
        record["location"] = detail.address
    if detail.land_area_sqm is not None:
        record["total_area_sqm"] = detail.land_area_sqm
    if detail.units_total is not None:
        record["total_units"] = detail.units_total
    if detail.proposed_completion_date is not None:
        # The filing's declared completion date is the date by which the promoter
        # must hand over possession. ``expiry_date`` stays what the register says
        # it is — the registration's validity — so the two dates never merge.
        record["possession_date"] = detail.proposed_completion_date


#: Columns the insert owns but the conflict update must not rewrite.
#:
#: ``rera_number`` is the conflict key. ``slug`` is a published URL key, so
#: rewriting it would break existing links. ``raw_data`` is owned by this scraper
#: on the rows it writes — no other writer touches ``rera_projects.raw_data`` — so
#: it is replaced rather than merged: a merge would keep a renamed key alive
#: forever. ``status`` is *not* protected: this register is the authority for
#: whether a Delhi project is registered, and a re-read must be able to refresh it.
_UPSERT_SKIP = {"id", "created_at", "updated_at", "last_checked_at", "last_successful_run_id"}
_UPDATE_SKIP = {"rera_number", "slug"}


class DelhiReraProjectScraper(BaseScraper):
    """Read the Delhi RERA register and each project's filing page."""

    name = "delhi_rera_projects"
    # Both pages are server-rendered; httpx is enough. See the module docstring.
    requires_playwright = False

    async def run(self, run_type: str = "cron", triggered_by: int | None = None) -> dict:
        if not settings.HRERA_DATA_ENABLED:
            return {
                "status": "disabled",
                "run_id": None,
                "reason": "hrera_disabled_by_configuration",
            }
        return await super().run(run_type=run_type, triggered_by=triggered_by)

    async def _scrape(self) -> ScrapeResult:
        if not settings.HRERA_DATA_ENABLED:
            return ScrapeResult()
        result = ScrapeResult()
        coverage: dict[str, Any] = {
            "source_url": _REGISTER_URL,
            "pages_attempted": 0,
            "pages_checked": 0,
            "pages_parsed": 0,
            "records_parsed": 0,
            "detail_pages_attempted": 0,
            "detail_pages_parsed": 0,
            "register_rows": 0,
            "mirror_rows": 0,
            "status": "failed",
        }

        coverage["pages_attempted"] += 1
        try:
            html = await self._fetch_url(_REGISTER_URL, timeout=_FETCH_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("Delhi RERA register fetch failed: %s", exc)
            result.errors.append(
                {
                    "source_url": _REGISTER_URL,
                    "stage": "fetch",
                    "error_type": type(exc).__name__,
                    "message": "Delhi RERA register fetch failed",
                }
            )
            result.source_coverage.append(coverage)
            return result
        coverage["pages_checked"] += 1
        checked_at = datetime.now(UTC)
        register_document = _register_source_document(html, checked_at=checked_at)
        result.source_documents.append(register_document)

        parsed = parse_registered_projects_html(html)
        coverage["register_rows"] = parsed.coverage.get("register_rows", 0)
        coverage["mirror_rows"] = parsed.coverage.get("mirror_rows", 0)
        for error in parsed.errors:
            result.errors.append({"source_url": _REGISTER_URL, **error})
        if not parsed.records:
            # A register that did not parse whole is not written at all: see the
            # module docstring on failing loudly.
            coverage["status"] = "failed"
            result.source_coverage.append(coverage)
            return result

        coverage["pages_parsed"] = 1
        coverage["records_parsed"] = len(parsed.records)

        for index, record in enumerate(parsed.records):
            filing_url = record["raw_data"]["detail_url"]
            project_id = record["raw_data"]["delhi_project_id"]
            if index:
                await asyncio.sleep(_DETAIL_DELAY_SECONDS)
            coverage["detail_pages_attempted"] += 1
            try:
                detail_html = await self._fetch_url(filing_url, timeout=_FETCH_TIMEOUT_SECONDS)
            except Exception as exc:
                logger.warning("Delhi RERA filing fetch failed for %s: %s", filing_url, exc)
                result.errors.append(
                    {
                        "source_url": filing_url,
                        "stage": "fetch",
                        "error_type": type(exc).__name__,
                        "message": "Delhi RERA filing fetch failed",
                    }
                )
                # The register row is still a complete record of what the
                # register states, so it is written without the filing's extras.
                record["_source_key"] = register_document["source_key"]
                record["_locator_page"] = 1
                record["_locator_row"] = record["raw_data"]["register_row"]
                result.records.append(record)
                continue
            detail_checked_at = datetime.now(UTC)
            detail_document = _detail_source_document(
                detail_html, url=filing_url, project_id=project_id, checked_at=detail_checked_at
            )
            result.source_documents.append(detail_document)
            detail = parse_project_detail_html(detail_html)
            for error in detail.errors:
                result.errors.append({"source_url": filing_url, **error})
            _apply_detail(record, detail)
            coverage["detail_pages_parsed"] += 1
            record["_source_key"] = detail_document["source_key"]
            # The profile and cost rows written from this filing cite the document
            # it was read from, so `_upsert` can resolve its id in the same
            # transaction rather than waiting for the provenance pass.
            record["_source_document"] = detail_document
            record["_locator_page"] = 1
            record["_locator_row"] = record["raw_data"]["register_row"]
            result.records.append(record)

        result.successful_sources = 1
        coverage["status"] = "partial" if result.errors else "success"
        result.source_coverage.append(coverage)
        return result

    async def _upsert(self, db: AsyncSession, records: list[dict[str, Any]]) -> dict:
        """Write the register rows, keyed on the registration number.

        The conflict target is ``rera_number`` — the registration number the
        register states — and not the portal project id. See the module docstring
        for why the portal id is kept out of ``raw_data.portal_project_id``.
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
                values = {
                    key: value
                    for key, value in rec.items()
                    if hasattr(ReraProject, key) and key not in _UPSERT_SKIP
                }
                async with db.begin_nested():
                    stmt = pg_insert(ReraProject).values(**values)
                    update_fields = {
                        key: getattr(stmt.excluded, key)
                        for key in values
                        if key not in _UPDATE_SKIP
                    }
                    result = await db.execute(
                        stmt.on_conflict_do_update(
                            index_elements=["rera_number"],
                            set_=update_fields,
                            # An older read must not overwrite a newer one, so the
                            # update only lands on a row this run has not already
                            # been beaten to.
                            where=or_(
                                ReraProject.last_checked_at.is_(None),
                                ReraProject.last_checked_at <= source_checked_at,
                            ),
                        ).returning(ReraProject.id)
                    )
                    project_id = result.scalar_one_or_none()
                    if project_id is None:
                        # A newer read already owns this row, so this run's filing
                        # is the older of the two. Writing it would walk the stored
                        # profile backwards.
                        continue
                    # The filing's own figures land in the same nested transaction
                    # as the register row, so a project is never left with half a
                    # read: either both are stored or neither is.
                    await self._write_filing(db, project_id, rec, source_checked_at)
                upserted += 1
                rec["_upsert_succeeded"] = True
            except Exception as e:
                logger.warning(
                    "Failed to upsert Delhi RERA project %s: %s", rec.get("rera_number"), e
                )
                failed += 1
        return {"found": found, "upserted": upserted, "failed": failed}

    async def _write_filing(
        self, db: AsyncSession, project_id: int, rec: dict[str, Any], checked_at: datetime
    ) -> None:
        """Write one filing's own profile row.

        The register states a project's identity; the filing states its figures.
        The project-intelligence surface reads ``rera_project_profiles`` —
        ``GET /projects/{slug}`` joins it — so a filing kept only under
        ``raw_data.detail`` is fetched, stored, and never shown. Delhi publishes a
        completion date for 121 of its 133 projects, and a tower inventory and land
        area for most of them; without this those pages render a project with no
        stage and no tower count while the same page for a Haryana project shows
        both.

        Only what the filing states is written. ``stage`` comes from
        ``derive_stage`` over the filed dates, exactly as the Haryana filing does,
        so a project whose completion date has passed while the register still
        lists it as live gets no stage rather than a guessed one.

        **The project cost is deliberately not written.** Delhi's field is labelled
        ``Project Cost (in rupees)`` and rendered as ``<value> (INR)``, but the
        values are not credible as rupees: 92 of the 120 projects that state one
        state ``1.00``, which is a placeholder rather than a cost, and the largest
        states ``249885954900000.00`` (₹249 trillion). The ones in between are the
        magnitude of *lakhs* — the municipal press project states ``1650.00`` for a
        60-unit building, which is ₹1,650 as rupees and ₹16.5 crore as lakhs. The
        unit is not knowable from the page, so publishing the figure would put a
        number wrong by orders of magnitude on a public project page. It stays in
        ``raw_data.detail``, where a reader can see exactly what the register
        stated, and the cost row stays unwritten until the portal's unit question
        is settled.
        """
        from app.models.data_hub import ReraProjectProfile
        from app.services.data_hub.provenance import get_or_create_source_document
        from app.services.data_hub.rera_project_detail import (
            derive_stage,
            derive_units_per_acre,
        )

        detail = (rec.get("raw_data") or {}).get("detail") or {}
        land_area_sqm = rec.get("total_area_sqm")
        total_units = rec.get("total_units")
        start_date = _parse_iso_date(detail.get("start_date"))
        completion_date = _parse_iso_date(detail.get("proposed_completion_date"))

        document_id: int | None = None
        source_document = rec.get("_source_document")
        if isinstance(source_document, dict):
            document_id = await get_or_create_source_document(
                db, {k: v for k, v in source_document.items() if k != "source_key"}
            )

        profile = {
            "land_area_sqm": land_area_sqm,
            "towers": detail.get("towers"),
            "total_units": total_units,
            "units_per_acre": derive_units_per_acre(total_units, land_area_sqm),
            "construction_start_date": start_date,
            "proposed_completion_date": completion_date,
            "stage": derive_stage(
                register_status=rec.get("status"),
                construction_start_date=start_date,
                proposed_completion_date=completion_date,
            ),
        }
        await self._upsert_one(
            db, ReraProjectProfile, "rera_project_id", project_id, profile, document_id, checked_at
        )


def _parse_iso_date(value: Any) -> date | None:
    """The date an ISO string names, or ``None`` when it is absent or unreadable."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
