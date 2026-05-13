"""Auction alert matching — finds new auctions matching user alert preferences."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_hub import AuctionAlert, BankAuction, CourtAuction
from app.services.data_hub.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class AlertMatcherService(BaseScraper):
    """
    Matches newly added auctions against user alert preferences.
    Runs after bank_auctions and court_auctions scrapers complete.
    Dispatches notifications via email (FCM/push is a future extension).
    """
    name = "alerts"

    async def _scrape(self) -> list[dict]:
        """Find auction-alert matches. Returns list of match dicts."""
        from app.core.database import get_bg_session_factory
        session_factory = get_bg_session_factory()
        async with session_factory() as db:
            return await self._find_matches(db)

    async def _find_matches(self, db: AsyncSession) -> list[dict]:
        """Get active alerts, find matching new auctions added in last 24h."""
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        # Get all active alerts
        result = await db.execute(
            select(AuctionAlert).where(AuctionAlert.is_active == True)  # noqa: E712
        )
        alerts = result.scalars().all()
        if not alerts:
            return []

        matches = []
        for alert in alerts:
            # Build filter for bank auctions
            filters = [BankAuction.created_at >= since, BankAuction.is_active == True]  # noqa: E712
            if alert.bank_name:
                filters.append(BankAuction.bank_name.ilike(f"%{alert.bank_name}%"))
            if alert.property_type:
                filters.append(BankAuction.property_type == alert.property_type)
            if alert.min_price is not None:
                filters.append(BankAuction.reserve_price >= alert.min_price)
            if alert.max_price is not None:
                filters.append(BankAuction.reserve_price <= alert.max_price)

            bank_result = await db.execute(
                select(BankAuction).where(and_(*filters)).limit(10)
            )
            new_bank_auctions = bank_result.scalars().all()

            # Build filter for court auctions
            court_filters = [CourtAuction.created_at >= since, CourtAuction.is_active == True]  # noqa: E712
            if alert.property_type:
                court_filters.append(CourtAuction.property_type == alert.property_type)
            if alert.min_price is not None:
                court_filters.append(CourtAuction.reserve_price >= alert.min_price)
            if alert.max_price is not None:
                court_filters.append(CourtAuction.reserve_price <= alert.max_price)

            court_result = await db.execute(
                select(CourtAuction).where(and_(*court_filters)).limit(10)
            )
            new_court_auctions = court_result.scalars().all()

            auctions: list[BankAuction | CourtAuction] = [*new_bank_auctions, *new_court_auctions]
            for auction in auctions:
                matches.append({
                    "alert_id": alert.id,
                    "user_id": alert.user_id,
                    "alert_channels": alert.alert_channels or ["email"],
                    "auction_id": auction.id,
                    "auction_type": "bank" if isinstance(auction, BankAuction) else "court",
                    "auction_description": getattr(auction, "property_description", ""),
                    "reserve_price": float(auction.reserve_price) if auction.reserve_price else None,
                })
        return matches

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        """Send notifications for matches. Currently logs; email dispatch is a stub."""
        found = len(records)
        dispatched = 0
        for match in records:
            try:
                await self._dispatch_notification(match)
                # Update last_notified_at on the alert
                alert_result = await db.execute(
                    select(AuctionAlert).where(AuctionAlert.id == match["alert_id"])
                )
                alert = alert_result.scalar_one_or_none()
                if alert:
                    alert.last_notified_at = datetime.now(timezone.utc)
                dispatched += 1
            except Exception as e:
                logger.warning("Failed to dispatch alert %s: %s", match.get("alert_id"), e)
        await db.commit()
        return {"found": found, "upserted": dispatched, "failed": found - dispatched}

    async def _dispatch_notification(self, match: dict) -> None:
        """Stub: log the match. Email/FCM integration to be implemented."""
        logger.info(
            "ALERT MATCH: user=%s alert=%s auction=%s type=%s price=%s",
            match["user_id"], match["alert_id"],
            match["auction_id"], match["auction_type"],
            match.get("reserve_price"),
        )
        # TODO: integrate with email service when EMAIL_SMTP_HOST is configured
