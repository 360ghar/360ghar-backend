"""Auction alert matching — finds new auctions matching user alert preferences."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, exists, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_hub import AuctionAlert, AuctionAlertDelivery, BankAuction, CourtAuction
from app.services.data_hub.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


def _delivered(alert_id: int, auction_type: str, auction_id_column):
    """True when this auction was already sent for this alert."""
    return exists().where(
        AuctionAlertDelivery.alert_id == alert_id,
        AuctionAlertDelivery.auction_type == auction_type,
        AuctionAlertDelivery.auction_id == auction_id_column,
    )


class AlertMatcherService(BaseScraper):
    """
    Matches newly added auctions against user alert preferences.
    Runs after bank_auctions and court_auctions scrapers complete.
    Dispatches notifications through the shared notification dispatcher
    (push, email, and in-app per the user's settings).
    """

    name = "alerts"

    async def _scrape(self) -> list[dict]:
        """Find auction-alert matches. Returns list of match dicts."""
        from app.core.database import get_bg_session_factory

        session_factory = get_bg_session_factory()
        async with session_factory() as db:
            return await self._find_matches(db)

    async def _find_matches(self, db: AsyncSession) -> list[dict]:
        """Get active alerts, find matching auctions added in the last 24h and not yet sent.

        An auction already sent for an alert has an ``AuctionAlertDelivery`` row and
        is skipped. A failed send writes no row, so the next run retries it. Matches
        are read oldest first, at most 10 per auction table per alert per run.
        """
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
            filters = [
                BankAuction.created_at >= since,
                ~_delivered(alert.id, "bank", BankAuction.id),
                BankAuction.is_active == True,  # noqa: E712
            ]
            if alert.city:
                filters.append(BankAuction.city.ilike(f"%{alert.city}%"))
            if alert.keyword:
                filters.append(BankAuction.property_description.ilike(f"%{alert.keyword}%"))
            if alert.bank_name:
                filters.append(BankAuction.bank_name.ilike(f"%{alert.bank_name}%"))
            if alert.property_type:
                filters.append(BankAuction.property_type == alert.property_type)
            if alert.min_price is not None:
                filters.append(BankAuction.reserve_price >= alert.min_price)
            if alert.max_price is not None:
                filters.append(BankAuction.reserve_price <= alert.max_price)

            bank_result = await db.execute(
                select(BankAuction)
                .where(and_(*filters))
                .order_by(BankAuction.created_at, BankAuction.id)
                .limit(10)
            )
            new_bank_auctions = bank_result.scalars().all()

            # Build filter for court auctions
            court_filters = [
                CourtAuction.created_at >= since,
                ~_delivered(alert.id, "court", CourtAuction.id),
                CourtAuction.is_active == True,  # noqa: E712
            ]
            if alert.city:
                court_filters.append(CourtAuction.city.ilike(f"%{alert.city}%"))
            if alert.keyword:
                court_filters.append(CourtAuction.property_description.ilike(f"%{alert.keyword}%"))
            if alert.property_type:
                court_filters.append(CourtAuction.property_type == alert.property_type)
            if alert.min_price is not None:
                court_filters.append(CourtAuction.reserve_price >= alert.min_price)
            if alert.max_price is not None:
                court_filters.append(CourtAuction.reserve_price <= alert.max_price)

            court_result = await db.execute(
                select(CourtAuction)
                .where(and_(*court_filters))
                .order_by(CourtAuction.created_at, CourtAuction.id)
                .limit(10)
            )
            new_court_auctions = court_result.scalars().all()

            auctions: list[BankAuction | CourtAuction] = sorted(
                [*new_bank_auctions, *new_court_auctions], key=lambda a: a.created_at
            )
            for auction in auctions:
                matches.append(
                    {
                        "alert_id": alert.id,
                        "user_id": alert.user_id,
                        "auction_id": auction.id,
                        "auction_type": "bank" if isinstance(auction, BankAuction) else "court",
                        "auction_description": getattr(auction, "property_description", ""),
                        "reserve_price": float(auction.reserve_price)
                        if auction.reserve_price
                        else None,
                    }
                )
        return matches

    async def _upsert(self, db: AsyncSession, records: list[dict]) -> dict:
        """Send a notification for each match and record the delivery.

        Each delivery writes an ``AuctionAlertDelivery`` row and commits right
        away, so a crash cannot make the next run re-send it. A failed send writes
        nothing and is retried next run. The dispatcher reads the user and writes
        the inbox row, so it needs this session; each commit keeps the open
        transaction to one dispatch.
        """
        found = len(records)
        dispatched = 0
        for match in records:
            try:
                await self._dispatch_notification(db, match)
            except Exception as e:
                logger.warning("Failed to dispatch alert %s: %s", match.get("alert_id"), e)
                continue
            await db.execute(
                pg_insert(AuctionAlertDelivery)
                .values(
                    alert_id=match["alert_id"],
                    auction_type=match["auction_type"],
                    auction_id=match["auction_id"],
                )
                .on_conflict_do_nothing(constraint="uq_auction_alert_deliveries_key")
            )
            alert = await db.get(AuctionAlert, match["alert_id"])
            if alert is not None:
                alert.last_notified_at = datetime.now(timezone.utc)
            await db.commit()
            dispatched += 1
        return {"found": found, "upserted": dispatched, "failed": found - dispatched}

    async def _dispatch_notification(self, db: AsyncSession, match: dict) -> None:
        """Dispatch the auction match to its user through the notification dispatcher.

        ``auction_alert_match`` is a registered type, so the dispatcher resolves its
        channels; an unregistered key would send nothing. A dispatch that reports an
        error raises, so the caller's per-match ``try/except`` counts it as failed and
        one user's failure never aborts the batch.
        """
        from app.services.notification_dispatcher import (
            dispatch_failure,
            dispatch_notification_to_user,
        )

        auction_type = match["auction_type"]
        result = await dispatch_notification_to_user(
            db,
            user_db_id=match["user_id"],
            type_key="auction_alert_match",
            title="New auction matches your alert",
            body=(
                f"A new {auction_type} auction matches your alert: "
                f"{match.get('auction_description') or 'property details available on the site'}."
            ),
            data={
                "alert_id": str(match["alert_id"]),
                "auction_id": str(match["auction_id"]),
                "auction_type": str(auction_type),
            },
        )
        failure = dispatch_failure(result)
        if failure:
            raise RuntimeError(f"notification dispatch failed: {failure}")
