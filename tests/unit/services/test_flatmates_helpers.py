"""Unit tests for flatmates helpers: age buckets, profile-age resolution, peer payload privacy."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from app.services.flatmates.helpers import (
    _build_peer_payload,
    age_bucket_for_age,
    resolve_profile_age,
)


class TestAgeBucketForAge:
    """Exact ages map to privacy buckets; unknown age maps to None."""

    def test_bucket_boundaries(self):
        cases = {
            18: "18-24",
            24: "18-24",
            25: "25-30",
            30: "25-30",
            31: "31-35",
            35: "31-35",
            36: "36-40",
            40: "36-40",
            41: "41-45",
            45: "41-45",
            46: "46+",
            100: "46+",
        }
        for age, expected in cases.items():
            assert age_bucket_for_age(age) == expected, f"age {age}"

    def test_none_returns_none(self):
        assert age_bucket_for_age(None) is None


class TestResolveProfileAge:
    """Precedence: preferences.flatmates.age → flatmates_age → date_of_birth."""

    @staticmethod
    def _user(**kwargs) -> SimpleNamespace:
        defaults = {
            "preferences": {"flatmates": {}},
            "flatmates_age": None,
            "date_of_birth": None,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_preferences_age_wins(self):
        user = self._user(
            preferences={"flatmates": {"age": 25}},
            flatmates_age=30,
            date_of_birth=datetime(2000, 1, 1),
        )
        assert resolve_profile_age(user) == 25

    def test_preferences_age_float_and_string_coerced(self):
        assert resolve_profile_age(self._user(preferences={"flatmates": {"age": 25.9}})) == 25
        assert resolve_profile_age(self._user(preferences={"flatmates": {"age": "26"}})) == 26

    def test_preferences_age_non_numeric_ignored(self):
        user = self._user(
            preferences={"flatmates": {"age": "unknown"}},
            flatmates_age=31,
        )
        assert resolve_profile_age(user) == 31

    def test_flatmates_age_column_when_no_pref_age(self):
        user = self._user(
            preferences={"flatmates": {}},
            flatmates_age=40,
        )
        assert resolve_profile_age(user) == 40

    def test_dob_fallback_when_no_stored_age(self):
        born = date(1990, 6, 15)
        today = date.today()
        expected = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        user = self._user(date_of_birth=datetime(1990, 6, 15))
        assert resolve_profile_age(user) == expected

    def test_none_when_nothing_available(self):
        assert resolve_profile_age(self._user()) is None


def _peer_user(**overrides) -> SimpleNamespace:
    defaults = {
        "id": 10,
        "full_name": "Peer User",
        "profile_image_url": None,
        "flatmates_mode": "seeker",
        "flatmates_city": "Mumbai",
        "flatmates_locality": "Bandra",
        "flatmates_bio": None,
        "flatmates_budget_min": 10000,
        "flatmates_budget_max": 25000,
        "flatmates_move_in_timeline": "this_month",
        "flatmates_sleep_schedule": "night_owl",
        "flatmates_cleanliness": "tidy",
        "flatmates_food_habits": "vegetarian",
        "flatmates_smoking": "never",
        "flatmates_drinking": "occasionally",
        "native_place": "Pune",
        "linkedin_url": "https://linkedin.com/in/peer",
        "flatmates_guests_policy": "occasional_ok",
        "flatmates_work_style": "hybrid",
        "phone": "+919999999999",
        "flatmates_age": 28,
        "date_of_birth": None,
        "preferences": {
            "flatmates": {
                "profession": "Engineer",
                "pets": "no_pets",
                "parties_at_home": "never",
                "gender": "female",
                "non_negotiables": ["no_smoking"],
            }
        },
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestPeerPayloadPrivacy:
    """Peer payloads expose an age bucket, never the exact age."""

    def test_exact_age_not_exposed(self):
        payload = _build_peer_payload(_peer_user(flatmates_age=28))
        assert "age" not in payload
        assert payload["age_bucket"] == "25-30"

    def test_exact_age_never_exposed_even_when_dob_known(self):
        user = _peer_user(
            flatmates_age=None,
            date_of_birth=datetime(1995, 6, 15),
            preferences={"flatmates": {}},
        )
        payload = _build_peer_payload(user)
        assert "age" not in payload
        assert payload["age_bucket"] is not None

    def test_new_profile_fields_exposed(self):
        payload = _build_peer_payload(_peer_user())
        assert payload["smoking"] == "never"
        assert payload["drinking"] == "occasionally"
        assert payload["native_place"] == "Pune"
        assert payload["linkedin_url"] == "https://linkedin.com/in/peer"

    def test_unknown_age_yields_null_bucket(self):
        payload = _build_peer_payload(_peer_user(flatmates_age=None, preferences={"flatmates": {}}))
        assert "age" not in payload
        assert payload["age_bucket"] is None
