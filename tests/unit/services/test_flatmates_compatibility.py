"""Unit tests for the flatmates compatibility engine."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.flatmates.compatibility import (
    calculate_compatibility,
    calculate_compatibility_score,
    calculate_property_compatibility_score,
    score_viewer_owner_compatibility,
    snapshot_user_for_compat,
    user_has_lifestyle_profile,
)


def _user(**kwargs: object) -> SimpleNamespace:
    defaults = {
        "id": 1,
        "flatmates_sleep_schedule": None,
        "flatmates_cleanliness": None,
        "flatmates_food_habits": None,
        "flatmates_smoking_drinking": None,
        "flatmates_guests_policy": None,
        "flatmates_work_style": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestCompatibilityIncompleteProfiles:
    def test_no_comparable_dimensions_returns_none_percentage(self):
        a = _user(id=1)
        b = _user(id=2)
        result = calculate_compatibility(a, b)  # type: ignore[arg-type]
        assert result["percentage"] is None
        assert result["dimensions"]
        assert all("not enough data" in s for s in result["summary"])
        assert calculate_compatibility_score(a, b) is None  # type: ignore[arg-type]

    def test_partial_profile_renormalizes_over_comparable_dims(self):
        a = _user(
            id=1,
            flatmates_sleep_schedule="early_bird",
            flatmates_cleanliness="tidy",
        )
        b = _user(
            id=2,
            flatmates_sleep_schedule="early_bird",
            flatmates_cleanliness="tidy",
        )
        result = calculate_compatibility(a, b)  # type: ignore[arg-type]
        # Only sleep (0.2) and cleanliness (0.2) comparable — both 100 → 100%
        assert result["percentage"] == 100
        assert result["color"] == "green"
        assert calculate_compatibility_score(a, b) == 100.0  # type: ignore[arg-type]

    def test_missing_on_one_side_excluded_from_score(self):
        a = _user(
            id=1,
            flatmates_sleep_schedule="early_bird",
            flatmates_food_habits="vegetarian",
        )
        b = _user(
            id=2,
            flatmates_sleep_schedule="night_owl",
            # food_habits missing on peer — must not drag score to 0 overall
        )
        result = calculate_compatibility(a, b)  # type: ignore[arg-type]
        # Only sleep comparable: distance 2 on ordered scale → 0
        assert result["percentage"] == 0
        assert result["color"] == "red"

    def test_user_has_lifestyle_profile(self):
        empty = _user(id=1)
        filled = _user(id=2, flatmates_work_style="remote")
        assert user_has_lifestyle_profile(empty) is False  # type: ignore[arg-type]
        assert user_has_lifestyle_profile(filled) is True  # type: ignore[arg-type]
        assert user_has_lifestyle_profile(None) is False


class TestSnapshotUserForCompat:
    def test_none_returns_none(self):
        assert snapshot_user_for_compat(None) is None

    def test_copies_id_and_lifestyle_fields(self):
        source = _user(
            id=42,
            flatmates_sleep_schedule="early_bird",
            flatmates_cleanliness="tidy",
            flatmates_work_style="remote",
        )
        snap = snapshot_user_for_compat(source)  # type: ignore[arg-type]
        assert snap is not None
        assert snap.id == 42
        assert snap.flatmates_sleep_schedule == "early_bird"
        assert snap.flatmates_cleanliness == "tidy"
        assert snap.flatmates_work_style == "remote"
        assert snap.flatmates_food_habits is None

    def test_snapshot_is_independent_of_source_mutation(self):
        source = _user(id=7, flatmates_guests_policy="open_house")
        snap = snapshot_user_for_compat(source)  # type: ignore[arg-type]
        assert snap is not None
        source.flatmates_guests_policy = "no_overnight_guests"
        source.id = 999
        assert snap.id == 7
        assert snap.flatmates_guests_policy == "open_house"

    def test_scoring_uses_snapshot_without_orm_session(self):
        """Mirrors the property-search fix: score from a plain snapshot after
        the session would have detached the original User instance."""
        viewer = _user(
            id=1,
            flatmates_sleep_schedule="early_bird",
            flatmates_cleanliness="spotless",
        )
        owner = _user(
            id=2,
            flatmates_sleep_schedule="early_bird",
            flatmates_cleanliness="spotless",
        )
        viewer_snap = snapshot_user_for_compat(viewer)  # type: ignore[arg-type]
        assert viewer_snap is not None
        assert user_has_lifestyle_profile(viewer_snap) is True  # type: ignore[arg-type]
        # Detach simulation: drop the original "ORM" reference; only snapshot remains.
        del viewer
        score = calculate_property_compatibility_score(viewer_snap, owner)  # type: ignore[arg-type]
        assert score == 100.0
        assert viewer_snap.id != owner.id

    def test_snapshot_returns_none_when_attribute_access_fails(self):
        """Detached/expired ORM User must not raise out of snapshot_user_for_compat."""

        class _BrokenOwner:
            @property
            def id(self):  # noqa: ANN201
                raise RuntimeError("Instance is not bound to a Session")

        assert snapshot_user_for_compat(_BrokenOwner()) is None  # type: ignore[arg-type]

    def test_score_viewer_owner_compatibility_snapshots_owner(self):
        viewer = _user(
            id=1,
            flatmates_sleep_schedule="early_bird",
            flatmates_cleanliness="spotless",
        )
        owner = _user(
            id=2,
            flatmates_sleep_schedule="early_bird",
            flatmates_cleanliness="spotless",
        )
        viewer_snap = snapshot_user_for_compat(viewer)  # type: ignore[arg-type]
        score = score_viewer_owner_compatibility(
            viewer_snap,
            owner_id=2,
            owner=owner,  # type: ignore[arg-type]
            viewer_id=1,
        )
        assert score == 100.0

    def test_score_viewer_owner_compatibility_skips_self_and_missing(self):
        viewer = _user(id=1, flatmates_work_style="remote")
        viewer_snap = snapshot_user_for_compat(viewer)  # type: ignore[arg-type]
        assert (
            score_viewer_owner_compatibility(
                viewer_snap, owner_id=1, owner=viewer, viewer_id=1  # type: ignore[arg-type]
            )
            is None
        )
        assert (
            score_viewer_owner_compatibility(
                viewer_snap, owner_id=None, owner=None, viewer_id=1
            )
            is None
        )
        assert (
            score_viewer_owner_compatibility(
                viewer_snap, owner_id=9, owner=None, viewer_id=1
            )
            is None
        )
