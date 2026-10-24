from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Literal

from app.models.enums import AppKey


class NotificationChannel(str, Enum):
    IN_APP = "in_app"
    PUSH = "push"
    EMAIL = "email"
    SMS = "sms"


class NotificationCategory(str, Enum):
    TRANSACTIONAL = "transactional"
    SYSTEM = "system"
    MARKETING = "marketing"


class NotificationPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class FrequencyCap:
    """Simple per-user frequency cap for a notification type."""

    per_day: int | None = None
    per_week: int | None = None


@dataclass(frozen=True)
class NotificationTypeConfig:
    """Configuration for a logical notification type.

    This defines how a given type should behave across channels and
    is used by the notification service when dispatching events.
    """

    key: str
    category: NotificationCategory
    priority: NotificationPriority
    allowed_channels: set[NotificationChannel] = field(default_factory=set)
    default_ttl_seconds: int = 24 * 3600
    frequency_cap: FrequencyCap | None = None


NOTIFICATION_TYPES: dict[str, NotificationTypeConfig] = {
    # Transactional / event-based
    "booking_confirmed": NotificationTypeConfig(
        key="booking_confirmed",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.HIGH,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=3 * 24 * 3600,
    ),
    "payment_failed": NotificationTypeConfig(
        key="payment_failed",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.CRITICAL,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
            NotificationChannel.SMS,
        },
        default_ttl_seconds=2 * 24 * 3600,
    ),
    "document_approved": NotificationTypeConfig(
        key="document_approved",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
        },
    ),
    "chat_message": NotificationTypeConfig(
        key="chat_message",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.HIGH,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=12 * 3600,
        frequency_cap=FrequencyCap(per_day=None),
    ),
    # System / important alerts
    "password_changed": NotificationTypeConfig(
        key="password_changed",
        category=NotificationCategory.SYSTEM,
        priority=NotificationPriority.CRITICAL,
        allowed_channels={
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=7 * 24 * 3600,
    ),
    "security_alert": NotificationTypeConfig(
        key="security_alert",
        category=NotificationCategory.SYSTEM,
        priority=NotificationPriority.CRITICAL,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
            NotificationChannel.SMS,
        },
        default_ttl_seconds=7 * 24 * 3600,
    ),
    "app_update": NotificationTypeConfig(
        key="app_update",
        category=NotificationCategory.SYSTEM,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.IN_APP,
            NotificationChannel.PUSH,
        },
        default_ttl_seconds=7 * 24 * 3600,
    ),
    "policy_update": NotificationTypeConfig(
        key="policy_update",
        category=NotificationCategory.SYSTEM,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=30 * 24 * 3600,
    ),
    # Marketing / lifecycle
    "promotion_generic": NotificationTypeConfig(
        key="promotion_generic",
        category=NotificationCategory.MARKETING,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=5 * 24 * 3600,
        frequency_cap=FrequencyCap(per_day=2, per_week=7),
    ),
    "discount_offer": NotificationTypeConfig(
        key="discount_offer",
        category=NotificationCategory.MARKETING,
        priority=NotificationPriority.HIGH,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
            NotificationChannel.SMS,
        },
        default_ttl_seconds=3 * 24 * 3600,
        frequency_cap=FrequencyCap(per_day=1, per_week=3),
    ),
    "win_back": NotificationTypeConfig(
        key="win_back",
        category=NotificationCategory.MARKETING,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=14 * 24 * 3600,
        frequency_cap=FrequencyCap(per_day=1, per_week=2),
    ),
    "upsell_suggestion": NotificationTypeConfig(
        key="upsell_suggestion",
        category=NotificationCategory.MARKETING,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=3 * 24 * 3600,
        frequency_cap=FrequencyCap(per_day=3, per_week=10),
    ),
    "onboarding_nudge": NotificationTypeConfig(
        key="onboarding_nudge",
        category=NotificationCategory.MARKETING,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.IN_APP,
            NotificationChannel.EMAIL,
        },
        default_ttl_seconds=7 * 24 * 3600,
        frequency_cap=FrequencyCap(per_day=1, per_week=3),
    ),
    "visit_reminder": NotificationTypeConfig(
        key="visit_reminder",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.HIGH,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.SMS,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=24 * 3600,
    ),
    "property_recommendation": NotificationTypeConfig(
        key="property_recommendation",
        category=NotificationCategory.MARKETING,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.IN_APP,
            NotificationChannel.EMAIL,
        },
        default_ttl_seconds=3 * 24 * 3600,
        frequency_cap=FrequencyCap(per_day=3, per_week=10),
    ),
    "daily_digest": NotificationTypeConfig(
        key="daily_digest",
        category=NotificationCategory.MARKETING,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=48 * 3600,
        frequency_cap=FrequencyCap(per_day=1, per_week=7),
    ),
    # Flatmates feature notifications
    "flatmate_new_message": NotificationTypeConfig(
        key="flatmate_new_message",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.HIGH,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=12 * 3600,
        frequency_cap=FrequencyCap(per_day=None),
    ),
    "flatmate_new_match": NotificationTypeConfig(
        key="flatmate_new_match",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.HIGH,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=24 * 3600,
    ),
    "flatmate_listing_approved": NotificationTypeConfig(
        key="flatmate_listing_approved",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=3 * 24 * 3600,
    ),
    "flatmate_listing_rejected": NotificationTypeConfig(
        key="flatmate_listing_rejected",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.HIGH,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=7 * 24 * 3600,
    ),
    "flatmate_account_suspended": NotificationTypeConfig(
        key="flatmate_account_suspended",
        category=NotificationCategory.SYSTEM,
        priority=NotificationPriority.CRITICAL,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=7 * 24 * 3600,
    ),
    "flatmate_account_warned": NotificationTypeConfig(
        key="flatmate_account_warned",
        category=NotificationCategory.SYSTEM,
        priority=NotificationPriority.HIGH,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=7 * 24 * 3600,
    ),
    "flatmate_report_actioned": NotificationTypeConfig(
        key="flatmate_report_actioned",
        category=NotificationCategory.SYSTEM,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=7 * 24 * 3600,
    ),
    "flatmate_report_dismissed": NotificationTypeConfig(
        key="flatmate_report_dismissed",
        category=NotificationCategory.SYSTEM,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=7 * 24 * 3600,
    ),
    "flatmate_visit_scheduled": NotificationTypeConfig(
        key="flatmate_visit_scheduled",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.HIGH,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.SMS,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=24 * 3600,
    ),
    "flatmate_visit_confirmed": NotificationTypeConfig(
        key="flatmate_visit_confirmed",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.HIGH,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.SMS,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=24 * 3600,
    ),
    # Data hub auction alerts. The user created the auction alert themselves, so
    # this is transactional: it must not sit behind the promotional-email consent.
    "auction_alert_match": NotificationTypeConfig(
        key="auction_alert_match",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.HIGH,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=3 * 24 * 3600,
        frequency_cap=FrequencyCap(per_day=5, per_week=20),
    ),
    # Data hub watchlist alerts. The user explicitly asked to track the project, so
    # these are transactional (not marketing): they must not be gated behind the
    # promotional-email consent, and the frequency caps only bound noise, never the
    # signal. TTLs are long because a price or possession move stays relevant for
    # weeks after the filing it came from.
    "watchlist_price_change": NotificationTypeConfig(
        key="watchlist_price_change",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.HIGH,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=14 * 24 * 3600,
        frequency_cap=FrequencyCap(per_day=3, per_week=10),
    ),
    "watchlist_stage_change": NotificationTypeConfig(
        key="watchlist_stage_change",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=14 * 24 * 3600,
        frequency_cap=FrequencyCap(per_day=2, per_week=7),
    ),
    "watchlist_possession_change": NotificationTypeConfig(
        key="watchlist_possession_change",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.HIGH,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=30 * 24 * 3600,
        frequency_cap=FrequencyCap(per_day=2, per_week=7),
    ),
    "watchlist_new_filing": NotificationTypeConfig(
        key="watchlist_new_filing",
        category=NotificationCategory.TRANSACTIONAL,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=30 * 24 * 3600,
        frequency_cap=FrequencyCap(per_day=3, per_week=15),
    ),
    # Fallback type for ad-hoc admin-triggered notifications
    "admin_broadcast": NotificationTypeConfig(
        key="admin_broadcast",
        category=NotificationCategory.SYSTEM,
        priority=NotificationPriority.NORMAL,
        allowed_channels={
            NotificationChannel.PUSH,
            NotificationChannel.IN_APP,
        },
        default_ttl_seconds=7 * 24 * 3600,
    ),
}

# Type keys accepted by the API. Generated from the registry, so a key that is not
# registered fails validation (422) instead of falling back to another type.
if TYPE_CHECKING:
    # Static checkers cannot follow a Literal built at runtime. Accept any str here.
    NotificationTypeKey = str
    MarketingTypeKey = str
else:
    NotificationTypeKey = Literal[tuple(NOTIFICATION_TYPES)]
    MarketingTypeKey = Literal[
        tuple(
            key
            for key, cfg in NOTIFICATION_TYPES.items()
            if cfg.category is NotificationCategory.MARKETING
        )
    ]

# Flatmates types go to flatmates devices only. Every other type goes to the ghar app.
_FLATMATES_TYPE_PREFIX = "flatmate_"


def app_key_for_type(type_key: str) -> AppKey:
    """Return the app whose devices receive a notification of ``type_key``."""
    return AppKey.flatmates if type_key.startswith(_FLATMATES_TYPE_PREFIX) else AppKey.ghar
