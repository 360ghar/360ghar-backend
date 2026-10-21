"""Find numbers and amounts in text and compare them with fact-sheet values.

Handles Devanagari digits, Indian grouping (1,25,000), lakh/crore words (English and
Hindi), area units (sqft, sq yd, sqm) and per-area rates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TOLERANCE = 0.005  # 0.5 percent
SQFT_PER_SQYD = 9.0
SQFT_PER_SQM = 10.7639

_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")

_MULTIPLIERS = {
    "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "लाख": 1e5,
    "crore": 1e7, "crores": 1e7, "cr": 1e7, "करोड़": 1e7, "करोड": 1e7,
    "thousand": 1e3, "k": 1e3, "हज़ार": 1e3, "हजार": 1e3,
    "million": 1e6, "billion": 1e9,
}  # fmt: skip
_AREA_UNITS = (
    r"sq\.?\s*ft\.?|sqft|square\s+feet|sq\.?\s*yd\.?s?|sq\.?\s*yards?|sqyd|gaj|"
    r"sq\.?\s*m(?![a-z])|sqm|square\s+met(?:er|re)s?|वर्ग\s*फुट|वर्ग\s*फ़ुट|वर्ग\s*गज|वर्ग\s*मीटर"
)
_TOKEN_RE = re.compile(
    r"(?P<cur>₹|rs\.?|inr)?\s*"
    r"(?P<num>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?P<mult>lakhs?|lacs?|crores?|cr\b|thousand|million|billion|k\b|लाख|करोड़|करोड|हज़ार|हजार))?"
    r"(?:\s*(?P<per>/|per\s+)?\s*(?P<area>" + _AREA_UNITS + r"))?"
    r"(?:\s*(?P<km>km\b|kilomet(?:er|re)s?\b|किमी|किलोमीटर))?"
    r"(?P<pct>\s*%)?",
    re.IGNORECASE,
)
_RANGE_GAP = re.compile(r"^\s*(?:-|–|—|to|से)\s*(?:₹|rs\.?|inr)?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Amount:
    value: float
    kind: str  # plain | inr | area | rate_area | km | pct
    text: str


def normalize_digits(text: str) -> str:
    return text.translate(_DEVANAGARI)


def extract_amounts(text: str) -> list[Amount]:
    """Return every number in ``text`` with units folded into the value."""
    text = normalize_digits(text)
    matches = list(_TOKEN_RE.finditer(text))
    mults: list[str | None] = [m.group("mult") for m in matches]
    # "2.5 - 8 crore": the first number shares the unit of the second.
    for i in range(len(matches) - 1):
        gap = text[matches[i].end() : matches[i + 1].start()]
        if mults[i] is None and mults[i + 1] and _RANGE_GAP.match(gap):
            mults[i] = mults[i + 1]
    out: list[Amount] = []
    for m, mult in zip(matches, mults, strict=True):
        raw = m.group("num").replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        if mult:
            value *= _MULTIPLIERS[mult.lower()]
        if m.group("area"):
            kind = "rate_area" if (m.group("per") or m.group("cur")) else "area"
        elif m.group("km"):
            kind = "km"
        elif m.group("pct"):
            kind = "pct"
        elif m.group("cur") or mult:
            kind = "inr"
        else:
            kind = "plain"
        out.append(Amount(value, kind, m.group(0).strip()))
    return out


def expand(amount: Amount) -> list[float]:
    """Equivalent values of one fact number: unit conversions a writer may use."""
    v = amount.value
    values = [v]
    if amount.kind == "area":
        values += [v / SQFT_PER_SQYD, v / SQFT_PER_SQM, v * SQFT_PER_SQYD, v * SQFT_PER_SQM]
    elif amount.kind == "rate_area":
        values += [v * SQFT_PER_SQYD, v * SQFT_PER_SQM, v / SQFT_PER_SQYD, v / SQFT_PER_SQM]
    elif amount.kind == "km":
        values.append(v * 1000)
    return values


def allowed_numbers(displays: list[str]) -> set[float]:
    allowed: set[float] = set()
    for display in displays:
        for amount in extract_amounts(display):
            allowed.update(expand(amount))
    return allowed


def matches(value: float, allowed: set[float]) -> bool:
    """True when ``value`` equals an allowed number within 0.5 percent."""
    for ref in allowed:
        if value == ref or (ref and abs(value - ref) <= TOLERANCE * abs(ref)):
            return True
    return False
