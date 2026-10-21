"""Find numbers and amounts in text and compare them with fact-sheet values.

Handles Devanagari digits, Indian grouping (1,25,000), lakh/crore words (English and
Hindi), area units (sq ft, sq yd, sq m), per-area rates, distances and spelled-out numbers.

Matching is by class: an amount of money only matches money, a distance only a distance,
and so on, so "0.5 km" in a fact never excuses "₹0.5 crore" in the text. Values of 10,000
or more match within 0.5 percent. Smaller values (counts, years, distances) match exactly.
Converted values (sq ft to sq m) are approximate, so they get the 0.5 percent tolerance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TOLERANCE = 0.005  # 0.5 percent
EXACT_BELOW = 10_000
SQFT_PER_SQYD = 9.0
SQFT_PER_SQM = 10.7639
_AREA_TO_SQFT = {"sqft": 1.0, "sqyd": SQFT_PER_SQYD, "sqm": SQFT_PER_SQM}

_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")

_MULTIPLIERS = {
    "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "लाख": 1e5,
    "crore": 1e7, "crores": 1e7, "cr": 1e7, "करोड़": 1e7, "करोड": 1e7,
    "thousand": 1e3, "k": 1e3, "हज़ार": 1e3, "हजार": 1e3,
    "million": 1e6, "billion": 1e9,
}  # fmt: skip
_AREA_UNITS = (
    r"sq\.?\s*ft\.?|sqft|square\s+feet|sq\.?\s*yd\.?s?|sq\.?\s*yards?|sqyd|gaj|"
    r"sq\.?\s*m(?![a-z])|sqm|square\s+met(?:er|re)s?|"
    r"वर्ग\s*फुट|वर्ग\s*फ़ुट|वर्ग\s*फीट|वर्ग\s*गज|वर्ग\s*यार्ड|वर्ग\s*मीटर"
)
# Indian (1,25,000) or western (12,345) grouping, else plain digits. "5,10" is two numbers.
_NUMBER = r"(?:\d{1,2}(?:,\d{2})+,\d{3}|\d{1,3}(?:,\d{3})+)(?:\.\d+)?|\d+(?:\.\d+)?"
_TOKEN_RE = re.compile(
    r"(?P<cur>₹|(?<![A-Za-z])(?:rs\.?|inr)(?![A-Za-z]))?\s*"
    rf"(?P<num>{_NUMBER})"
    r"(?:\s*(?P<mult>lakhs?|lacs?|crores?|cr\b|thousand|million|billion|k\b|लाख|करोड़|करोड|हज़ार|हजार))?"
    rf"(?:\s*(?P<per>/|per\s+|प्रति\s+)?\s*(?P<area>{_AREA_UNITS}))?"
    r"(?:\s*(?:(?P<km>km\b|kilomet(?:er|re)s?\b|किमी|किलोमीटर)|(?P<m>m\b|metres?\b|meters?\b|मीटर)))?"
    r"(?P<pct>\s*%)?",
    re.IGNORECASE,
)
_RANGE_GAP = re.compile(r"^\s*(?:-|–|—|to|से)\s*(?:₹|rs\.?|inr)?\s*$", re.IGNORECASE)

# Spelled-out numbers. "one" is left out: it is mostly a pronoun.
_WORD_NUMBERS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90,
}  # fmt: skip
_WORD_RE = re.compile(
    r"\b(?P<w>" + "|".join(_WORD_NUMBERS) + r")(?:\s+(?P<mult>lakhs?|crores?))?\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Amount:
    value: float  # money in rupees, area in sq ft, distance in km
    kind: str  # plain | money | area | rate | km | pct
    text: str
    approx: bool = False  # a converted value: use the 0.5 percent tolerance


# Allowed numbers by kind.
Allowed = dict[str, list[tuple[float, bool]]]


def normalize_digits(text: str) -> str:
    return text.translate(_DEVANAGARI)


def _area_key(unit: str) -> str:
    unit = unit.lower().replace(" ", "").replace(".", "")
    if "yd" in unit or "yard" in unit or "गज" in unit or "यार्ड" in unit:
        return "sqyd"
    if unit.endswith("m") or "met" in unit or "मीटर" in unit or unit == "sqm":
        return "sqm"
    return "sqft"


def extract_amounts(text: str) -> list[Amount]:
    """Return every number in ``text`` with units folded into the value."""
    text = normalize_digits(text)
    matches = list(_TOKEN_RE.finditer(text))
    mults: list[str | None] = [m.group("mult") for m in matches]
    areas: list[tuple[str | None, str | None]] = [(m.group("area"), m.group("per")) for m in matches]
    # "2.5 - 8 crore", "₹58,230 to ₹1.14 lakh per sq yd": the first number shares the unit of the second.
    for i in range(len(matches) - 1):
        gap = text[matches[i].end() : matches[i + 1].start()]
        if not _RANGE_GAP.match(gap):
            continue
        # Only a small first number takes the unit: "85 - 90 lakh", but not "58,230 to 1.14 lakh".
        if mults[i] is None and mults[i + 1] and float(matches[i].group("num").replace(",", "")) < 1000:
            mults[i] = mults[i + 1]
        if areas[i][0] is None and areas[i + 1][0]:
            areas[i] = areas[i + 1]
    out: list[Amount] = []
    for m, mult, (area, per) in zip(matches, mults, areas, strict=True):
        value = float(m.group("num").replace(",", ""))
        if mult:
            value *= _MULTIPLIERS[mult.lower()]
        if area:
            sqft_factor = _AREA_TO_SQFT[_area_key(area)]
            converted = sqft_factor != 1.0  # a conversion makes the value approximate
            if per or m.group("cur"):
                out.append(Amount(value / sqft_factor, "rate", m.group(0).strip(), converted))  # per sq ft
            else:
                out.append(Amount(value * sqft_factor, "area", m.group(0).strip(), converted))  # sq ft
            continue
        if m.group("km"):
            kind = "km"
        elif m.group("m"):
            kind, value = "km", value / 1000
        elif m.group("pct"):
            kind = "pct"
        elif m.group("cur") or mult:
            kind = "money"
        else:
            kind = "plain"
        out.append(Amount(value, kind, m.group(0).strip()))
    for w in _WORD_RE.finditer(text):
        value = float(_WORD_NUMBERS[w.group("w").lower()])
        if w.group("mult"):
            out.append(Amount(value * _MULTIPLIERS[w.group("mult").lower()], "money", w.group(0)))
        else:
            out.append(Amount(value, "plain", w.group(0)))
    return out


def allowed_numbers(displays: list[str]) -> Allowed:
    allowed: Allowed = {}
    for display in displays:
        for amount in extract_amounts(display):
            allowed.setdefault(amount.kind, []).append((amount.value, amount.approx))
    return allowed


def matches(amount: Amount, allowed: Allowed) -> bool:
    """True when the amount equals an allowed number of the same kind."""
    for ref, ref_approx in allowed.get(amount.kind, []):
        if amount.value == ref:
            return True
        tolerant = amount.approx or ref_approx or abs(ref) >= EXACT_BELOW
        if tolerant and ref and abs(amount.value - ref) <= TOLERANCE * abs(ref):
            return True
    return False
