"""Wave 3d drift pass: the model column declarations match the migrated database.

The drift check (scripts/verify_schema_drift.py) compares the models with a migrated
database and needs CONTRACT_DRIFT_DATABASE_URL. These tests pin the same decisions on the
model metadata alone, so they run in every environment and a model edit that reopens a
drift line fails here first.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.database import Base
from app.models.enums import UserMatchStatus
from app.models.social import EnumStringType


def _col(ref: str) -> sa.Column:
    table, column = ref.split(".")
    return Base.metadata.tables[table].c[column]


def _impl(col: sa.Column) -> sa.types.TypeEngine:
    return col.type.impl if isinstance(col.type, sa.types.TypeDecorator) else col.type


# The database holds these ids as BIGINT (BIGSERIAL primary keys and BIGINT foreign keys).
BIGINT_COLUMNS = [
    "agents.id",
    "app_catalogs.id",
    "bookings.id",
    "bookings.property_id",
    "bookings.user_id",
    "flatmate_profile_view_events.id",
    "flatmate_super_like_usage.id",
    "match_qna_answers.id",
    "match_qna_answers.match_id",
    "match_qna_answers.user_id",
    "properties.current_tenant_id",
    "properties.id",
    "properties.owner_id",
    "property_images.id",
    "property_images.property_id",
    "tour_analytics_events.id",
    "user_blocks.id",
    "user_matches.id",
    "user_reports.id",
    "user_search_history.id",
    "user_search_history.user_id",
    "user_swipes.id",
    "user_swipes.property_id",
    "user_swipes.user_id",
    "users.agent_id",
    "users.id",
    "visits.agent_id",
    "visits.id",
    "visits.match_id",
    "visits.property_id",
    "visits.user_id",
]

# The database holds these foreign keys as INTEGER. Without an explicit type SQLAlchemy takes
# the type of the target column, which is now BigInteger, so each one is pinned to Integer.
# Widening them is a table rewrite per column. The values fit int4.
INT4_FK_COLUMNS = [
    "ai_jobs.user_id",
    "bug_reports.assigned_to",
    "bug_reports.user_id",
    "capture_sessions.user_id",
    "conversation_participants.user_id",
    "conversations.created_by_user_id",
    "custom_domains.user_id",
    "flatmate_profile_view_events.context_property_id",
    "flatmate_profile_view_events.viewed_user_id",
    "flatmate_profile_view_events.viewer_user_id",
    "flatmate_super_like_usage.target_user_id",
    "flatmate_super_like_usage.user_id",
    "media_files.user_id",
    "messages.sender_id",
    "pages.created_by",
    "pages.updated_by",
    "property_amenities.property_id",
    "tour_analytics_events.user_id",
    "tours.user_id",
    "user_blocks.blocked_user_id",
    "user_blocks.blocker_user_id",
    "user_matches.context_property_id",
    "user_matches.user_one_id",
    "user_matches.user_two_id",
    "user_reports.property_id",
    "user_reports.reported_user_id",
    "user_reports.reporter_user_id",
    "user_swipes.context_property_id",
    "user_swipes.target_user_id",
    "visits.counterparty_user_id",
]

JSONB_COLUMNS = [
    "agents.languages",
    "agents.working_hours",
    "app_catalogs.payload",
    "bank_auctions.raw_data",
    "bank_rates.raw_data",
    "bookings.guest_details",
    "circle_rates.raw_data",
    "colony_approvals.raw_data",
    "court_auctions.raw_data",
    "gazette_notifications.raw_data",
    "gazette_notifications.relevance_tags",
    "jamabandi_cache.owner_names",
    "neighbourhood_scores.category_scores",
    "neighbourhood_scores.hospitals",
    "neighbourhood_scores.it_parks",
    "neighbourhood_scores.landmarks",
    "neighbourhood_scores.malls",
    "neighbourhood_scores.metro_stations",
    "neighbourhood_scores.nearby_places",
    "neighbourhood_scores.schools",
    "rera_complaints.raw_data",
    "rera_projects.raw_data",
    "scraper_runs.metadata",
    "user_search_history.search_filters",
    "zoning_data.raw_data",
]

TEXT_COLUMNS = [
    "app_catalogs.key",
    "user_matches.status",
    "user_reports.reason",
    "user_reports.status",
]

DOUBLE_COLUMNS = [
    "agents.user_satisfaction_rating",
    "user_search_history.user_location_lat",
    "user_search_history.user_location_lng",
]

# The database has a DEFAULT for each one. The migration 20261015002002 sets NOT NULL.
NOT_NULL_COLUMNS = [
    "agent_interactions.created_at",
    "agents.created_at",
    "agents.is_active",
    "agents.is_available",
    "agents.total_users_assigned",
    "agents.user_satisfaction_rating",
    "ai_jobs.progress",
    "ai_jobs.retry_count",
    "bookings.created_at",
    "bookings.early_check_in",
    "bookings.late_check_out",
    "custom_domains.created_at",
    "custom_domains.updated_at",
    "floor_plans.floor_number",
    "hotspots.is_active",
    "media_files.is_processed",
    "media_files.visibility",
    "scenes.is_processed",
    "tours.is_featured",
    "tours.is_public",
    "tours.like_count",
    "tours.share_count",
    "tours.view_count",
    "user_search_history.created_at",
    "user_swipes.created_at",
    "visits.created_at",
    "visits.follow_up_required",
    "visits.status",
]


@pytest.mark.parametrize("ref", BIGINT_COLUMNS)
def test_id_columns_are_bigint_like_the_database(ref: str) -> None:
    assert isinstance(_impl(_col(ref)), sa.BigInteger)


@pytest.mark.parametrize("ref", INT4_FK_COLUMNS)
def test_int4_foreign_keys_stay_integer_like_the_database(ref: str) -> None:
    impl = _impl(_col(ref))
    assert isinstance(impl, sa.Integer) and not isinstance(impl, sa.BigInteger)


@pytest.mark.parametrize("ref", JSONB_COLUMNS)
def test_json_columns_are_jsonb_like_the_database(ref: str) -> None:
    assert isinstance(_impl(_col(ref)), JSONB)


@pytest.mark.parametrize("ref", TEXT_COLUMNS)
def test_string_columns_are_text_like_the_database(ref: str) -> None:
    assert isinstance(_impl(_col(ref)), sa.Text)


@pytest.mark.parametrize("ref", DOUBLE_COLUMNS)
def test_measure_columns_are_double_precision(ref: str) -> None:
    impl = _impl(_col(ref))
    assert isinstance(impl, sa.Float)
    assert impl.precision is None  # a precision of 24 or less would be REAL


@pytest.mark.parametrize("ref", NOT_NULL_COLUMNS)
def test_columns_with_a_default_are_declared_not_null(ref: str) -> None:
    assert _col(ref).nullable is False


@pytest.mark.parametrize("column", ["agent_id", "user_id"])
def test_agent_interactions_cascade_with_agent_and_user(column: str) -> None:
    """Interaction rows are child records. The database cascades, so the model says so."""
    (fk,) = _col(f"agent_interactions.{column}").foreign_keys
    assert fk.ondelete == "CASCADE"


def test_enum_string_type_is_text_and_still_validates_writes() -> None:
    column_type = EnumStringType(UserMatchStatus)
    assert isinstance(column_type.impl_instance, sa.Text)
    assert column_type.process_bind_param(UserMatchStatus.active, None) == "active"
    assert column_type.process_bind_param("blocked", None) == "blocked"
    with pytest.raises(ValueError, match="Invalid UserMatchStatus"):
        column_type.process_bind_param("nonsense", None)
