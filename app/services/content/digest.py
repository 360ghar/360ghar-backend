"""Weekly market digest from data-hub changes, saved through the blog service.

The data hub keeps no value history, so a "change" is a row created or updated in the last
seven days: new RERA registrations, new bank auctions, circle rate rows touched. Fewer than
MIN_CHANGES changes means no post. The text goes through the same validator as locality
content. A post that validates is published (when MARKET_DIGEST_AUTO_PUBLISH is on); any
other post is saved as a draft tagged needs-review.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.logging import get_logger
from app.core.utils import utc_now
from app.models.blogs import BlogPost
from app.models.data_hub import BankAuction, CircleRate, ReraProject
from app.models.enums import BlogPostStatus, UserRole
from app.models.users import User
from app.schemas.blog import BlogPostCreate, BlogSource
from app.services.ai.base import AIProvider
from app.services.blog import create_blog_post
from app.services.content import runner
from app.services.content.facts import Fact, FactSheet, inr

logger = get_logger(__name__)

MIN_CHANGES = 3
WINDOW_DAYS = 7


def _day(d: date | datetime) -> str:
    return f"{d.day} {d:%B %Y}"


async def build_digest_sheet(db: AsyncSession, today: date) -> tuple[FactSheet, int, list[str]]:
    """The digest fact sheet, the number of changes in it, and source URLs for the post."""
    since = datetime.combine(today - timedelta(days=WINDOW_DAYS), datetime.min.time(), tzinfo=utc_now().tzinfo)
    now = today.isoformat()
    sheet = FactSheet("digest", f"digest-{today.isocalendar().year}-w{today.isocalendar().week:02d}",
                      "Gurugram market digest", "Gurugram")
    urls: list[str] = []
    sheet.add(Fact("period", "Period covered", f"{_day(today - timedelta(days=WINDOW_DAYS))} to {_day(today)}",
                   "360 Ghar data hub", now, "context"))

    rera = (
        await db.execute(
            select(ReraProject.project_name, ReraProject.developer_name, ReraProject.location,
                   ReraProject.total_units, ReraProject.source_url)
            .where(ReraProject.created_at >= since)
            .order_by(ReraProject.total_units.desc().nulls_last(), ReraProject.project_name)
        )
    ).all()
    if rera:
        sheet.add(Fact("rera_new", "New RERA registrations", str(len(rera)), "HRERA registry", now, "rera"))
        top = rera[:5]
        sheet.add(
            Fact("rera_top", "Largest new registrations",
                 "; ".join(f"{r.project_name} by {r.developer_name or 'an unnamed developer'}"
                           + (f" in {r.location}" if r.location else "")
                           + (f", {r.total_units} units" if r.total_units else "") for r in top),
                 "HRERA registry", now, "rera"),
            *(x for r in top for x in (r.project_name, r.developer_name, r.location) if x),
        )
        urls += [r.source_url for r in top if r.source_url]

    auctions = (
        await db.execute(
            select(BankAuction.bank_name, BankAuction.locality, BankAuction.reserve_price,
                   BankAuction.auction_date, BankAuction.source_url)
            .where(BankAuction.created_at >= since, BankAuction.is_active.is_(True))
            .order_by(BankAuction.auction_date.nulls_last())
        )
    ).all()
    if auctions:
        prices = [float(a.reserve_price) for a in auctions if a.reserve_price]
        sheet.add(Fact("auction_new", "New bank auction listings", str(len(auctions)), "Bank auction notices",
                       now, "price"))
        if prices:
            sheet.add(Fact("auction_range", "Reserve price range of new auctions",
                           inr(min(prices)) if min(prices) == max(prices) else f"{inr(min(prices))} to {inr(max(prices))}",
                           "Bank auction notices", now, "price"))
        banks = sorted({a.bank_name for a in auctions if a.bank_name})[:5]
        places = sorted({a.locality for a in auctions if a.locality})[:5]
        if banks:
            sheet.add(Fact("auction_banks", "Banks with new auctions", ", ".join(banks),
                           "Bank auction notices", now, "price"), *banks)
        if places:
            sheet.add(Fact("auction_places", "Areas with new auctions", ", ".join(places),
                           "Bank auction notices", now, "price"), *places)
        dated = [a.auction_date for a in auctions if a.auction_date]
        if dated:
            sheet.add(Fact("auction_next", "Earliest new auction date", _day(min(dated)),
                           "Bank auction notices", now, "price"))
        urls += [a.source_url for a in auctions[:3] if a.source_url]

    circle = (
        await db.execute(
            select(CircleRate.sector, CircleRate.revision_year)
            .where(CircleRate.updated_at >= since)
            .order_by(CircleRate.sector)
        )
    ).all()
    if circle:
        sectors = sorted({c.sector for c in circle})
        sheet.add(Fact("circle_updated", "Circle rate rows updated", str(len(circle)),
                       "Haryana circle rates", now, "circle_rate"))
        sheet.add(Fact("circle_sectors", "Areas with updated circle rates", ", ".join(sectors[:6]),
                       "Haryana circle rates", now, "circle_rate"), *sectors[:6])
    return sheet, len(rera) + len(auctions) + len(circle), list(dict.fromkeys(urls))[:6]


def _html(output: dict[str, Any], sheet: FactSheet) -> str:
    parts = [f"<p>{escape(output['summary'])}</p>"]
    for sec in output["sections"]:
        parts.append(f"<h2>{escape(sec['heading'])}</h2><p>{escape(sec['body'])}</p>")
    sources = ", ".join(escape(s["name"] or "") for s in sheet.sources())
    parts.append(f"<p>Sources: {sources}. Data as of {sheet.data_as_of:%d %B %Y}.</p>")
    return "\n".join(parts)


async def _publisher(db: AsyncSession) -> User | None:
    uid = settings.AUTO_BLOG_PUBLISHER_USER_ID
    user = await db.get(User, uid) if uid is not None else None
    return user if user is not None and user.role == UserRole.admin.value else None


async def generate_market_digest(
    db: AsyncSession, provider: AIProvider, today: date | None = None, throttle: runner.Throttle | None = None
) -> dict[str, Any]:
    today = today or utc_now().date()
    sheet, changes, urls = await build_digest_sheet(db, today)
    if changes < MIN_CHANGES:
        return {"status": "skipped", "reason": "fewer_than_3_changes", "changes": changes}
    publisher = await _publisher(db)
    if publisher is None:
        return {"status": "skipped", "reason": "no_publisher_user", "changes": changes}
    week_start = today - timedelta(days=WINDOW_DAYS)
    title = f"Gurugram property data digest: week of {_day(week_start)}"
    exists = (await db.execute(select(func.count(BlogPost.id)).where(BlogPost.title == title))).scalar_one()
    if exists:
        return {"status": "exists", "reason": "digest_already_saved", "changes": changes}

    gen = await runner.generate(provider, sheet, "en", throttle)
    if gen.output is None:
        return {"status": "failed", "reason": "no_output", "changes": changes, "errors": gen.errors}
    out = gen.output
    publish = gen.ok and settings.MARKET_DIGEST_AUTO_PUBLISH
    payload = BlogPostCreate(
        title=title,
        content=_html(out, sheet) if gen.ok else f"<p>{escape(str(out.get('summary', 'Draft')))}</p>",
        excerpt=str(out.get("summary", ""))[:1000],
        categories=["Market Updates"],
        tags=["market-digest", "gurugram", "data-hub"] + ([] if gen.ok else ["needs-review"]),
        meta_title=title[:60],
        meta_description=str(out.get("meta_description", ""))[:155] or None,
        focus_keyword="Gurugram property market",
        cover_image_url=None,
        canonical_url=None,
        og_image_url=None,
        seo_metadata=None,
        published_at=None,
        sources=[BlogSource(url=u, name="Source", type="data", retrieved_at=today.isoformat()) for u in urls],
        status=BlogPostStatus.published if publish else BlogPostStatus.draft,
    )
    post = await create_blog_post(db, payload, publisher)
    await db.commit()
    return {
        "status": "published" if publish else "draft",
        "reason": None if gen.ok else "validation_failed",
        "changes": changes,
        "post_slug": post.slug,
        "errors": gen.errors,
        "calls": gen.calls,
    }
