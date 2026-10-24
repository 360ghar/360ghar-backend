"""Deterministic fact sheets. The model may use only what is listed here.

Every fact carries a display string, a source and an as_of date. The validator checks
generated numbers and names against these facts, so a fact sheet is the single source of
truth for one entity. Nothing in this module calls a model.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.utils import utc_now
from app.models.content import Locality
from app.models.data_hub import BankAuction, CircleRate, ReraProject
from app.models.enums import PropertyPurpose, PropertyStatus
from app.models.properties import Amenity, Property, PropertyAmenity, PropertyImage
from app.services.content.numbers import Allowed, allowed_numbers

SNAPSHOT = Path(__file__).parent / "data" / "locality_seed.json"

# A page needs this many facts, and one price-like fact, to be offered to search engines.
MIN_FACTS_FOR_INDEX = 6
KEY_GROUPS = frozenset({"price", "circle_rate", "rera"})

# Names the writer may always use.
BASE_NAMES = frozenset(
    {
        "360 Ghar", "Gurugram", "Gurgaon", "Haryana", "India", "Delhi", "NCR", "Delhi NCR",
        "BHK", "RERA", "HRERA", "HSVP", "HUDA", "DLF", "Indian", "English", "Hindi",
    }
)  # fmt: skip
_CITY_ALIASES = {"gurugram": ("gurugram", "gurgaon"), "gurgaon": ("gurugram", "gurgaon")}


@dataclass(frozen=True)
class Fact:
    key: str
    label: str
    display: str
    source: str
    as_of: str | None = None
    group: str = "context"
    url: str | None = None


@dataclass
class FactSheet:
    entity_type: str
    slug: str
    name: str
    city: str
    facts: list[Fact] = field(default_factory=list)
    names: set[str] = field(default_factory=set)
    quoted_text: str | None = None  # user-written listing text, passed to the model as data
    salt: str = ""  # other inputs that change the output but are not facts (photo URLs)

    def add(self, fact: Fact | None, *names: str) -> None:
        if fact is not None:
            self.facts.append(fact)
        self.names.update(n for n in names if n)

    @property
    def fact_count(self) -> int:
        """Facts about this entity. City-wide ranges are shown to the model but do not count."""
        return sum(1 for f in self.facts if f.group != "city_price")

    @property
    def key_fact(self) -> bool:
        return any(f.group in KEY_GROUPS for f in self.facts)

    @property
    def meets_threshold(self) -> bool:
        return self.fact_count >= MIN_FACTS_FOR_INDEX and self.key_fact

    @property
    def data_as_of(self) -> date | None:
        dates = [f.as_of for f in self.facts if f.as_of]
        return date.fromisoformat(max(dates)) if dates else None

    def allowed_names(self) -> set[str]:
        return {*BASE_NAMES, self.name, self.city, *self.names}

    def allowed_numbers(self) -> Allowed:
        shown = [f.display for f in self.facts]
        # A date may be quoted by year only. Owner-written titles never add numbers.
        shown += [f.as_of[:4] for f in self.facts if f.as_of]
        if self.entity_type == "locality":
            shown.append(self.name)
        return allowed_numbers(shown)

    def facts_hash(self) -> str:
        # Everything the prompt carries: facts (label and value), allowed names, owner text.
        payload = json.dumps(
            [(f.key, f.label, f.display) for f in self.facts] + [sorted(self.names), self.quoted_text, self.salt],
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def sources(self) -> list[dict[str, str | None]]:
        seen: dict[str, dict[str, str | None]] = {}
        for f in self.facts:
            seen.setdefault(f.source, {"name": f.source, "url": f.url, "as_of": f.as_of})
        return list(seen.values())

    def prompt_facts(self) -> list[dict[str, str | None]]:
        return [
            {"id": f.key, "fact": f"{f.label}: {f.display}", "source": f.source, "as_of": f.as_of}
            for f in self.facts
        ]


def inr(value: float | Decimal) -> str:
    x = float(value)
    if x >= 1e7 or round(x / 1e5, 2) >= 100:  # 99.999 lakh rounds up to 1 crore, not 100 lakh
        return f"₹{x / 1e7:.2f} crore"
    if x >= 1e5:
        return f"₹{x / 1e5:.2f} lakh"
    return f"₹{x:,.0f}"


_UNIT = re.compile(r"\b(lakhs?|crores?)\b", re.IGNORECASE)


def money_range(text: str) -> str:
    """'85 lakhs - 3.5 crore' -> '₹85 lakh to ₹3.5 crore'; '15,000 - 85,000/month' -> per month."""
    suffix = ""
    if text.endswith("/month"):
        text, suffix = text[: -len("/month")], " per month"
    parts = [p.strip() for p in text.split(" - ")]
    unit = _UNIT.search(parts[-1])
    out = []
    for p in parts:
        if unit and not _UNIT.search(p):
            p = f"{p} {unit.group(1)}"
        out.append("₹" + re.sub(r"\blakhs\b", "lakh", p, flags=re.IGNORECASE))
    return " to ".join(out) + suffix


def _range(lo: float, hi: float) -> str:
    return inr(lo) if round(lo) == round(hi) else f"{inr(lo)} to {inr(hi)}"


@lru_cache(maxsize=1)
def snapshot() -> dict[str, Any]:
    return json.loads(SNAPSHOT.read_text())  # type: ignore[no-any-return]


def _lower_names(loc: Locality) -> list[str]:
    return sorted({n.lower() for n in [loc.name, *(loc.aliases or [])] if n})


def _city_variants(city: str) -> list[str]:
    return list(_CITY_ALIASES.get(city.lower(), (city.lower(),)))


def _price_context_key(city: str) -> str:
    return "gurgaon" if city.lower() in ("gurugram", "gurgaon") else city.lower()


async def build_locality_sheet(db: AsyncSession, loc: Locality, today: date | None = None) -> FactSheet:
    today = today or utc_now().date()
    now = today.isoformat()
    names = _lower_names(loc)
    cities = _city_variants(loc.city)
    sheet = FactSheet("locality", loc.slug, loc.name, loc.city)
    sheet.names.update(loc.aliases or [])
    sheet.add(
        Fact("place", "Place", f"{loc.name} is a {loc.place_type} in {loc.city}, Haryana"
             if loc.city == "Gurugram" else f"{loc.name} is a {loc.place_type} in {loc.city}",
             "360 Ghar locality data", snapshot()["generated_on"], "geo")
    )

    for i, lm in enumerate(loc.landmarks or []):
        sheet.add(
            Fact(f"landmark_{i + 1}", "Nearby", f"{lm['name']} ({lm['type']}), {lm['distance']}",
                 "360 Ghar locality data", snapshot()["generated_on"], "geo"),
            lm["name"],
        )

    # Live listings in this locality.
    match = or_(func.lower(Property.locality).in_(names), func.lower(Property.sub_locality).in_(names))
    live = and_(
        match,
        func.lower(Property.city).in_(cities),
        Property.status == PropertyStatus.available,
        Property.is_available.is_(True),
    )
    for purpose, col, key, label in (
        (PropertyPurpose.buy, Property.base_price, "sale", "For sale"),
        (PropertyPurpose.rent, Property.monthly_rent, "rent", "For rent"),
    ):
        row = (
            await db.execute(
                select(
                    func.count(),
                    func.min(col),
                    func.max(col),
                    func.percentile_cont(0.5).within_group(col),
                ).where(live, Property.purpose == purpose, col.is_not(None), col > 0)
            )
        ).one()
        count, lo, hi, median = row
        if not count:
            continue
        suffix = " per month" if key == "rent" else ""
        sheet.add(Fact(f"listings_{key}", f"{label}: active listings on 360 Ghar", str(count),
                       "360 Ghar listings", now, "listing"))
        # Medians and ranges of one or two listings say little: state the price plainly.
        if count == 1:
            sheet.add(Fact(f"price_{key}", f"{label}: listed price", inr(lo) + suffix,
                           "360 Ghar listings", now, "price"))
            continue
        sheet.add(Fact(f"price_{key}", f"{label}: listed price range",
                       _range(float(lo), float(hi)) + suffix, "360 Ghar listings", now, "price"))
        if count >= 3:
            sheet.add(Fact(f"median_{key}", f"{label}: median listed price",
                           inr(median) + suffix, "360 Ghar listings", now, "price"))
    psf_row = (
        await db.execute(
            select(func.count(), func.percentile_cont(0.5).within_group(Property.base_price / Property.area_sqft)).where(
                live, Property.purpose == PropertyPurpose.buy, Property.area_sqft > 0, Property.base_price > 0
            )
        )
    ).one()
    psf = psf_row[1] if psf_row[0] >= 3 else None
    if psf:
        sheet.add(Fact("median_psf", "For sale: median price per sq ft", f"₹{float(psf):,.0f} per sq ft",
                       "360 Ghar listings", now, "price"))
    beds = (
        await db.execute(
            select(Property.bedrooms).where(live, Property.bedrooms.is_not(None), Property.bedrooms > 0)
            .distinct().order_by(Property.bedrooms)
        )
    ).scalars().all()
    if beds:
        sheet.add(Fact("bhk_options", "BHK options currently listed",
                       ", ".join(f"{b} BHK" for b in beds), "360 Ghar listings", now, "listing"))

    # Government circle rates, one fact per land use (a residential rate is not a commercial one).
    # Only the newest revision counts: an older revision is an obsolete rate.
    matched = and_(
        func.lower(CircleRate.district).in_(cities),
        or_(func.lower(CircleRate.sector).in_(names), func.lower(CircleRate.colony).in_(names)),
        CircleRate.rate_per_sqyd.is_not(None),
    )
    newest = (await db.execute(select(func.max(CircleRate.revision_year)).where(matched))).scalar()
    circle = (
        await db.execute(
            select(
                CircleRate.property_type, func.min(CircleRate.rate_per_sqyd),
                func.max(CircleRate.rate_per_sqyd), func.max(CircleRate.source_url),
            )
            .where(matched, CircleRate.revision_year == newest)
            .group_by(CircleRate.property_type)
            .order_by(CircleRate.property_type.desc())
        )
    ).all()
    for ptype, lo, hi, url in circle:
        sheet.add(Fact(f"circle_rate_{ptype}", f"Government circle rate, {ptype} (revision {newest})",
                       f"{_range(float(lo), float(hi))} per sq yd", "Haryana circle rates", f"{newest}-04-01",
                       "circle_rate", url))

    if settings.HRERA_DATA_ENABLED:
        # RERA registered projects whose location names this place.
        pattern = "|".join(r"\m" + re.escape(n) + r"\M" for n in names)
        rera_rows = (
            await db.execute(
                select(
                    ReraProject.project_name,
                    ReraProject.developer_name,
                    ReraProject.total_units,
                    ReraProject.complaint_count,
                )
                .where(
                    func.lower(ReraProject.district).in_(cities),
                    ReraProject.location.op("~*")(pattern),
                )
                .order_by(ReraProject.total_units.desc().nulls_last(), ReraProject.project_name)
            )
        ).all()
        if rera_rows:
            top = rera_rows[:5]
            sheet.add(
                Fact(
                    "rera_count",
                    "RERA registered projects in the area",
                    str(len(rera_rows)),
                    "HRERA registry",
                    now,
                    "rera",
                )
            )
            sheet.add(
                Fact(
                    "rera_projects",
                    "Larger registered projects",
                    ", ".join(r.project_name for r in top),
                    "HRERA registry",
                    now,
                    "rera",
                ),
                *(r.project_name for r in top),
            )
            developers = sorted({r.developer_name for r in top if r.developer_name})
            if developers:
                sheet.add(
                    Fact(
                        "rera_developers",
                        "Developers of those projects",
                        ", ".join(developers),
                        "HRERA registry",
                        now,
                        "rera",
                    ),
                    *developers,
                )
            units = sum(r.total_units or 0 for r in rera_rows)
            if units:
                sheet.add(
                    Fact(
                        "rera_units",
                        "Total units across registered projects",
                        f"{units:,}",
                        "HRERA registry",
                        now,
                        "rera",
                    )
                )

    auctions = (
        await db.execute(
            select(func.count(), func.min(BankAuction.reserve_price), func.max(BankAuction.reserve_price))
            .where(BankAuction.is_active.is_(True), func.lower(BankAuction.locality).in_(names),
                   func.lower(BankAuction.city).in_([*cities, "delhi ncr"]))
        )
    ).one()
    if auctions[0]:
        sheet.add(Fact("bank_auctions", "Active bank auctions",
                       f"{auctions[0]}" + (f", reserve prices {_range(float(auctions[1]), float(auctions[2]))}"
                                           if auctions[1] else ""),
                       "Bank auction notices", now, "price"))

    city_ctx = snapshot()["price_context"].get(_price_context_key(loc.city))
    if city_ctx:
        sheet.add(Fact("city_buy_range", f"Typical apartment price range across {loc.city} (editorial estimate)",
                       money_range(city_ctx["buy"]["apartment"]), "360 Ghar market ranges",
                       snapshot()["generated_on"], "city_price"))
        sheet.add(Fact("city_rent_range", f"Typical apartment rent range across {loc.city} (editorial estimate)",
                       money_range(city_ctx["rent"]["apartment"]), "360 Ghar market ranges",
                       snapshot()["generated_on"],
                       "city_price"))
    return sheet


_PTYPE_LABEL = {"builder_floor": "builder floor", "pg": "PG"}


async def build_property_sheet(db: AsyncSession, property_id: int, today: date | None = None) -> FactSheet | None:
    now = (today or utc_now().date()).isoformat()
    prop = (
        await db.execute(
            select(Property).where(
                Property.id == property_id,
                Property.status == PropertyStatus.available,
                Property.is_available.is_(True),
            )
        )
    ).scalar_one_or_none()
    if prop is None:
        return None
    ptype = _PTYPE_LABEL.get(prop.property_type.value, prop.property_type.value)
    place = ", ".join(x for x in (prop.sub_locality, prop.locality, prop.city) if x)
    # The owner's title is untrusted text: it goes only into quoted_text, never into the entity name.
    sheet = FactSheet("property", str(prop.id), f"{ptype} in {place or 'an unlisted place'}", prop.city or "")
    src = "360 Ghar listing"

    def add(key: str, label: str, display: str | None, group: str = "listing", *names: str) -> None:
        if display:
            sheet.add(Fact(key, label, display, src, now, group), *names)

    purpose = prop.purpose.value
    add("kind", "Listing", f"{ptype} for {'sale' if purpose == 'buy' else purpose.replace('_', ' ')}")
    add("location", "Location", place or None, "listing", *(x for x in (prop.sub_locality, prop.locality, prop.city) if x))
    # Each purpose has its own price column. Never quote a sale price for a rental.
    if purpose == "rent" and prop.monthly_rent:
        add("price", "Rent", f"{inr(prop.monthly_rent)} per month", "price")
    elif purpose == "short_stay" and prop.daily_rate:
        add("price", "Nightly rate", f"{inr(prop.daily_rate)} per night", "price")
    elif purpose == "buy" and prop.base_price:
        add("price", "Price", inr(prop.base_price), "price")
    if prop.price_per_sqft and purpose == "buy":
        add("psf", "Price per sq ft", f"₹{float(prop.price_per_sqft):,.0f} per sq ft", "price")
    if prop.security_deposit:
        add("deposit", "Security deposit", inr(prop.security_deposit), "price")
    if prop.maintenance_charges:
        add("maintenance", "Maintenance charges", f"{inr(prop.maintenance_charges)} per month", "price")
    if prop.area_sqft:
        add("area", "Built-up area", f"{prop.area_sqft:,.0f} sq ft")
    if prop.bedrooms:
        add("bedrooms", "Bedrooms", f"{prop.bedrooms} BHK")
    if prop.bathrooms:
        add("bathrooms", "Bathrooms", str(prop.bathrooms))
    if prop.balconies:
        add("balconies", "Balconies", str(prop.balconies))
    if prop.parking_spaces:
        add("parking", "Parking spaces", str(prop.parking_spaces))
    if prop.floor_number is not None and prop.total_floors:
        add("floor", "Floor", f"floor {prop.floor_number} of {prop.total_floors}")
    if prop.age_of_property is not None:
        add("age", "Age of property", f"{prop.age_of_property} years")
    add("furnishing", "Furnishing", prop.furnishing_level.replace("_", " ") if prop.furnishing_level else None)
    if prop.builder_name:
        add("builder", "Builder", prop.builder_name, "listing", prop.builder_name)
    amenity_titles = (
        await db.execute(
            select(Amenity.title).join(PropertyAmenity, PropertyAmenity.amenity_id == Amenity.id)
            .where(PropertyAmenity.property_id == prop.id).order_by(Amenity.title).limit(12)
        )
    ).scalars().all()
    if amenity_titles:
        add("amenities", "Amenities", ", ".join(amenity_titles), "listing", *amenity_titles)

    # Owner-written text is data, never instructions. Its names may be used, its numbers may not.
    sheet.quoted_text = "\n".join(x for x in (prop.title, prop.description) if x)[:1500] or None
    photos = (
        await db.execute(
            select(PropertyImage.image_url).where(PropertyImage.property_id == prop.id)
            .order_by(PropertyImage.is_main_image.desc(), PropertyImage.display_order, PropertyImage.id).limit(3)
        )
    ).scalars().all()
    sheet.salt = "|".join(photos)
    sheet.names.update(re.findall(r"[A-Z][a-z][\w'’-]*", prop.title or ""))  # words like Godrej, not shouting
    return sheet
