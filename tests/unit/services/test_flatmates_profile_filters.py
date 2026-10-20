from app.models.enums import (
    Cleanliness,
    FlatmatesDrinkingType,
    FlatmatesSmokingType,
    FoodHabits,
    GuestsPolicy,
    SleepSchedule,
)
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
    members only — legacy aliases (veg, non_veg, balanced, neat_freak, no/none
    synonyms, before_7, no_overnight, retired combined smoking_drinking values)
    must NOT appear.

    This guards the deal-breaker block in list_discoverable_profiles against
    reintroducing loose-string synonyms now that the columns are strict PG enums.
    """
    # Canonical value sets, derived from the enums (single source of truth).
    food_canonical = {m.value for m in FoodHabits}
    smoke_canonical = {m.value for m in FlatmatesSmokingType} | {
        m.value for m in FlatmatesDrinkingType
    }
    guests_canonical = {m.value for m in GuestsPolicy}
    clean_canonical = {m.value for m in Cleanliness}
    sleep_canonical = {m.value for m in SleepSchedule}

    # food_veg_only / food_vegan_only
    assert {"vegetarian", "vegan"}.issubset(food_canonical)
    # no_smoking / no_drinking compare against the split enums' "never"
    assert {"never"}.issubset(smoke_canonical)
    # no_overnight_guests
    assert {"no_overnight_guests"}.issubset(guests_canonical)
    # min_tidy
    assert {"tidy", "spotless"}.issubset(clean_canonical)
    # early_riser
    assert {"early_bird"}.issubset(sleep_canonical)

    # Legacy aliases must NOT be canonical members.
    legacy = {
        "veg",
        "non_veg",
        "balanced",
        "neat_freak",
        "messy",
        "no",
        "none",
        "before_7",
        "no_overnight",
        "rarely",
        "socially",
        "frequently",
        "no_restrictions",
        # Retired combined smoking_drinking values (the column has no ORM mapping).
        "neither",
        "smoke_outside",
        "drink_occasionally",
        "both_fine",
    }
    all_canonical = (
        food_canonical | smoke_canonical | guests_canonical | clean_canonical | sleep_canonical
    )
    assert legacy.isdisjoint(all_canonical), (
        f"Legacy aliases leaked into canonical enum members: {legacy & all_canonical}"
    )
