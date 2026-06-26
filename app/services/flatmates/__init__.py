"""Flatmates service package — re-exports all public symbols for backward compatibility."""

from __future__ import annotations

from app.services.flatmates.conversations import (
    create_conversation_from_payload,
    get_conversation,
    get_conversation_summary,
    list_conversations,
    list_messages,
    mark_conversation_read,
    save_match_qna_answers,
    send_message,
)
from app.services.flatmates.helpers import geocode_listing
from app.services.flatmates.interactions import (
    record_profile_view_event,
    record_society_tag_vote,
)
from app.services.flatmates.matching import (
    list_incoming_likes,
    list_matches,
    list_outgoing_likes,
    record_swipe,
    unmatch_match,
    unmatch_user_pair,
)
from app.services.flatmates.moderation import (
    apply_listing_prescreen_metadata,
    apply_report_auto_pause,
    apply_stale_listing_pause,
    build_listing_prescreen_result,
    create_block,
    create_report,
    delete_block,
    list_blocks,
    pause_stale_flatmate_listings,
    prescreen_flatmate_listing,
)
from app.services.flatmates.profiles import (
    get_bootstrap,
    get_flatmates_profile,
    get_profile_by_id,
    list_catalogs,
    list_discoverable_profiles,
    list_flatmates_notifications,
    mark_all_flatmates_notifications_read,
    mark_flatmates_notification_read,
    update_flatmates_profile,
)
from app.services.flatmates.visits import update_visit_status

__all__ = [
    # profiles
    "get_flatmates_profile",
    "get_profile_by_id",
    "list_discoverable_profiles",
    "update_flatmates_profile",
    "list_catalogs",
    "list_flatmates_notifications",
    "mark_flatmates_notification_read",
    "mark_all_flatmates_notifications_read",
    "get_bootstrap",
    # matching
    "record_swipe",
    "list_incoming_likes",
    "list_outgoing_likes",
    "list_matches",
    "unmatch_user_pair",
    "unmatch_match",
    # conversations
    "get_conversation",
    "get_conversation_summary",
    "list_conversations",
    "list_messages",
    "send_message",
    "mark_conversation_read",
    "save_match_qna_answers",
    "create_conversation_from_payload",
    # interactions
    "record_profile_view_event",
    "record_society_tag_vote",
    # moderation
    "create_block",
    "delete_block",
    "list_blocks",
    "create_report",
    "build_listing_prescreen_result",
    "apply_stale_listing_pause",
    "apply_listing_prescreen_metadata",
    "apply_report_auto_pause",
    "pause_stale_flatmate_listings",
    "prescreen_flatmate_listing",
    # visits
    "update_visit_status",
    # helpers
    "geocode_listing",
]
