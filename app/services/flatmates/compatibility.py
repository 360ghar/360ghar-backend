"""Flatmate compatibility engine.

The algorithm mirrors the web engine in
``src/lib/compatibility/dimensions.ts`` so the backend, web, and mobile
surfaces return consistent scores. It compares six lifestyle dimensions with
weighted per-dimension scoring and produces an overall percentage, a per-dimension
breakdown, and top-match chips.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from app.models.users import User

DIMENSION_WEIGHTS = {
    "sleep_schedule": 0.2,
    "cleanliness": 0.2,
    "food_habits": 0.15,
    "smoking_drinking": 0.2,
    "guests_policy": 0.15,
    "work_style": 0.1,
}

DIMENSION_LABELS = {
    "sleep_schedule": "Sleep Schedule",
    "cleanliness": "Cleanliness",
    "food_habits": "Food Habits",
    "smoking_drinking": "Smoking/Drinking",
    "guests_policy": "Guests Policy",
    "work_style": "Work Style",
}

MATCH_THRESHOLD = 60

ORDERED_SCALES: dict[str, list[str]] = {
    "sleep_schedule": ["early_bird", "flexible", "night_owl"],
    "cleanliness": ["minimal", "tidy", "spotless"],
    "guests_policy": ["no_overnight_guests", "occasional_ok", "open_house"],
}


def _as_str(value: Any) -> str | None:
    """Normalize enum or string values to strings."""
    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    return str(value.value if hasattr(value, "value") else value) or None


def _get_dimension_value(user: User, dimension: str) -> str | None:
    """Read a flatmates dimension value from the user model."""
    return _as_str(getattr(user, f"flatmates_{dimension}", None))


def _score_ordered(user_value: str | None, peer_value: str | None, values: list[str]) -> float:
    """Score two values on an ordered scale."""
    if user_value is None or peer_value is None:
        return 0.0
    try:
        user_idx = values.index(user_value)
        peer_idx = values.index(peer_value)
    except ValueError:
        return 0.0
    distance = abs(user_idx - peer_idx)
    if distance == 0:
        return 100.0
    if distance == 1:
        return 50.0
    return 0.0


def _score_sleep_schedule(a: str | None, b: str | None) -> float:
    return _score_ordered(a, b, ORDERED_SCALES["sleep_schedule"])


def _score_cleanliness(a: str | None, b: str | None) -> float:
    return _score_ordered(a, b, ORDERED_SCALES["cleanliness"])


def _score_food_habits(a: str | None, b: str | None) -> float:
    if a is None or b is None:
        return 0.0
    if a == b:
        return 100.0
    if a == "no_preference" or b == "no_preference":
        return 70.0
    strict = {"vegetarian", "vegan"}
    a_strict = a in strict
    b_strict = b in strict
    if a_strict and b_strict:
        return 100.0
    if a_strict or b_strict:
        return 0.0
    return 80.0


def _score_smoking_drinking(a: str | None, b: str | None) -> float:
    if a is None or b is None:
        return 0.0
    if a == b:
        return 100.0
    if a == "both_fine" or b == "both_fine":
        return 70.0
    non_smoker = {"neither", "drink_occasionally"}
    if a in non_smoker and b in non_smoker:
        return 80.0
    return 30.0


def _score_guests_policy(a: str | None, b: str | None) -> float:
    if a is None or b is None:
        return 0.0
    values = ORDERED_SCALES["guests_policy"]
    try:
        user_idx = values.index(a)
        peer_idx = values.index(b)
    except ValueError:
        return 0.0
    distance = abs(user_idx - peer_idx)
    if distance == 0:
        return 100.0
    if distance == 1:
        return 60.0
    return 20.0


def _score_work_style(a: str | None, b: str | None) -> float:
    if a is None or b is None:
        return 0.0
    if a == b:
        return 100.0
    return 70.0


_SCORERS = {
    "sleep_schedule": _score_sleep_schedule,
    "cleanliness": _score_cleanliness,
    "food_habits": _score_food_habits,
    "smoking_drinking": _score_smoking_drinking,
    "guests_policy": _score_guests_policy,
    "work_style": _score_work_style,
}


def _overall_color(percentage: int) -> str:
    if percentage >= 70:
        return "green"
    if percentage >= 40:
        return "amber"
    return "red"


def _dimension_summary(dimension: str, score: float) -> str:
    label = DIMENSION_LABELS[dimension]
    if score >= 90:
        return f"{label}: strong match"
    if score >= MATCH_THRESHOLD:
        return f"{label}: workable match"
    return f"{label}: preference gap"


def user_has_lifestyle_profile(user: User | None) -> bool:
    """True when the user has at least one flatmates lifestyle dimension set."""
    if user is None:
        return False
    return any(_get_dimension_value(user, key) is not None for key in DIMENSION_WEIGHTS)


def snapshot_user_for_compat(user: User | None) -> SimpleNamespace | None:
    """Copy id + lifestyle fields into a session-independent namespace.

    Hold this across later DB work (including
    :func:`execute_with_transient_retry` session invalidation). Reusing an
    ORM ``User`` after the session is reset causes ``DetachedInstanceError``
    when compatibility scoring reads attributes.
    """
    if user is None:
        return None
    data: dict[str, Any] = {"id": user.id}
    for key in DIMENSION_WEIGHTS:
        attr = f"flatmates_{key}"
        data[attr] = getattr(user, attr, None)
    return SimpleNamespace(**data)


def calculate_compatibility(
    current_user: User | None,
    peer: User | None,
) -> dict[str, Any]:
    """Return a full compatibility breakdown between two users.

    The result dict contains:
      - percentage: int (0-100) or None when no dimensions are comparable
      - color: "green" | "amber" | "red"
      - dimensions: list of per-dimension dicts
      - summary: list of per-dimension human-readable summaries
      - top_match_chips: list of top matching dimension labels (max 3)

    Missing values do not count as 0% mismatches. Overall percentage is
    renormalized over dimensions where both sides have a value. When no
    dimensions are comparable, ``percentage`` is ``None`` (unknown), not 0.
    """
    if current_user is None or peer is None:
        return {
            "percentage": None,
            "color": "red",
            "dimensions": [],
            "summary": [],
            "top_match_chips": [],
        }

    dimensions: list[dict[str, Any]] = []
    weighted_sum = 0.0
    weight_total = 0.0

    for key, weight in DIMENSION_WEIGHTS.items():
        user_value = _get_dimension_value(current_user, key)
        peer_value = _get_dimension_value(peer, key)
        comparable = user_value is not None and peer_value is not None
        if comparable:
            scorer = _SCORERS[key]
            score = float(round(scorer(user_value, peer_value)))
            is_match = score >= MATCH_THRESHOLD
            summary_text = _dimension_summary(key, score)
            weighted_sum += score * weight
            weight_total += weight
        else:
            score = 0.0
            is_match = False
            summary_text = f"{DIMENSION_LABELS[key]}: not enough data"

        dimensions.append(
            {
                "name": key,
                "weight": weight,
                "user_value": user_value,
                "peer_value": peer_value,
                "score": score,
                "match": is_match,
                "summary": summary_text,
            }
        )

    if weight_total <= 0:
        percentage: int | None = None
        color = "red"
    else:
        percentage = int(round(weighted_sum / weight_total))
        color = _overall_color(percentage)

    top_matches = [
        DIMENSION_LABELS[dim["name"]]
        for dim in sorted(dimensions, key=lambda d: d["score"], reverse=True)
        if dim["match"]
    ][:3]

    summary = [dim["summary"] for dim in dimensions]

    return {
        "percentage": percentage,
        "color": color,
        "dimensions": dimensions,
        "summary": summary,
        "top_match_chips": top_matches,
    }


def calculate_compatibility_score(
    current_user: User | None,
    peer: User | None,
) -> float | None:
    """Return just the overall compatibility score, or None if not comparable."""
    if current_user is None or peer is None or current_user.id == peer.id:
        return None
    if not user_has_lifestyle_profile(current_user) or not user_has_lifestyle_profile(peer):
        return None
    result = calculate_compatibility(current_user, peer)
    percentage = result["percentage"]
    if percentage is None:
        return None
    return cast(float, percentage)


def calculate_property_compatibility_score(
    current_user: User | None,
    owner: User | None,
) -> float | None:
    """Compatibility score for a property listing, comparing viewer to owner."""
    return calculate_compatibility_score(current_user, owner)
