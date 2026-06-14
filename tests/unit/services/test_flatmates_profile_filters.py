from app.models.enums import Cleanliness, FoodHabits, GuestsPolicy, SleepSchedule, SmokingDrinking
from app.services.flatmates.profiles import _move_in_profile_values


def test_move_in_profile_values_normalize_catalog_aliases():
    assert _move_in_profile_values("immediate") == {
        "immediate",
        "immediately",
        "now",
    }
    assert _move_in_profile_values("within_1_month") == {
        "this_month",
        "within_1_month",
        "within_a_month",
    }


def test_move_in_profile_values_ignore_flexible_and_unknown_values():
    assert _move_in_profile_values("flexible") == set()
    assert _move_in_profile_values("unknown") == set()


def test_deal_breaker_filter_lists_use_only_canonical_enum_values():
    """The non-negotiables filter branches must compare against canonical enum
    members only — legacy aliases (veg, non_veg, balanced, neat_freak, neither
    synonyms like never/no/none, before_7, no_overnight) must NOT appear.

    This guards the deal-breaker block in list_discoverable_profiles against
    reintroducing loose-string synonyms now that the columns are strict PG enums.
    """
    # Canonical value sets, derived from the enums (single source of truth).
    food_canonical = {m.value for m in FoodHabits}
    smoke_canonical = {m.value for m in SmokingDrinking}
    guests_canonical = {m.value for m in GuestsPolicy}
    clean_canonical = {m.value for m in Cleanliness}
    sleep_canonical = {m.value for m in SleepSchedule}

    # food_veg_only / food_vegan_only
    assert {"vegetarian", "vegan"}.issubset(food_canonical)
    # no_smoking / no_drinking
    assert {"neither", "drink_occasionally"}.issubset(smoke_canonical)
    assert {"neither", "smoke_outside"}.issubset(smoke_canonical)
    # no_overnight_guests
    assert {"no_overnight_guests"}.issubset(guests_canonical)
    # min_tidy
    assert {"tidy", "spotless"}.issubset(clean_canonical)
    # early_riser
    assert {"early_bird"}.issubset(sleep_canonical)

    # Legacy aliases must NOT be canonical members.
    legacy = {
        "veg", "non_veg", "balanced", "neat_freak", "messy",
        "never", "no", "none", "before_7", "no_overnight", "rarely",
        "socially", "frequently", "no_restrictions",
    }
    all_canonical = food_canonical | smoke_canonical | guests_canonical | clean_canonical | sleep_canonical
    assert legacy.isdisjoint(all_canonical), (
        f"Legacy aliases leaked into canonical enum members: {legacy & all_canonical}"
    )
