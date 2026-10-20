"""Vastu LLM output with null or wrong-typed fields returns 200 with the documented default.

The provider call is the only patched step, so the real coercion, parsing and
response model run for each case. Each case changes one field.
"""

import copy
from collections.abc import Callable
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from PIL import Image

from app.services.ai.vastu.analyzer import DEFAULT_DISCLAIMER

BASE_PAYLOAD: dict = {
    "floor_plan_analysis": {
        "plot_shape": "rectangular",
        "rooms": [
            {"name": "Kitchen", "direction": "South-East", "notes": None},
            {"name": "Bedroom", "direction": "South-West"},
            {"name": "Bathroom", "direction": "North-West"},
        ],
        "entrance": {"direction": "North"},
        "kitchen": {"location": "south-east"},
        "toilets": {"count": 1, "directions": ["north-west"]},
        "staircase": None,
        "balconies": None,
        "open_spaces": None,
        "center_area": "clear",
        "compass_visible": True,
    },
    "vastu_score": 7,
    "score_explanation": "Good overall layout",
    "assumptions": ["North is at the top"],
    "room_analysis": [
        {"room": "Kitchen", "direction": "South-East", "status": "good", "analysis": "Fine"}
    ],
    "major_defects": [{"issue": "Toilet in north-east", "severity": "high", "impact": "Health"}],
    "remedies": [{"problem": "Toilet in north-east", "solution": "Move it", "type": "placement"}],
    "improvements": ["Add a plant"],
    "disclaimer": "For information only.",
    "is_valid_floor_plan": True,
}


def _set(path: list, value: object) -> Callable[[dict], None]:
    def apply(payload: dict) -> None:
        node = payload
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return apply


def _drop(path: list) -> Callable[[dict], None]:
    def apply(payload: dict) -> None:
        node = payload
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]

    return apply


# (case id, mutation of the LLM payload, check on response data["data"])
CASES: list[tuple[str, Callable[[dict], None], Callable[[dict], bool]]] = [
    (
        "room_name_null",
        _set(["floor_plan_analysis", "rooms", 0, "name"], None),
        lambda d: d["floor_plan_analysis"]["rooms"][0]["name"] == "Unknown",
    ),
    (
        "room_direction_wrong_type",
        _set(["floor_plan_analysis", "rooms", 1, "direction"], 5),
        lambda d: d["floor_plan_analysis"]["rooms"][1]["direction"] == "5",
    ),
    (
        "rooms_null",
        _set(["floor_plan_analysis", "rooms"], None),
        lambda d: d["floor_plan_analysis"]["rooms"] == [],
    ),
    (
        "entrance_direction_null",
        _set(["floor_plan_analysis", "entrance"], {"direction": None}),
        lambda d: d["floor_plan_analysis"]["entrance"]["direction"] == "Unknown",
    ),
    (
        "toilet_count_wrong_type",
        _set(["floor_plan_analysis", "toilets", "count"], "two"),
        lambda d: d["floor_plan_analysis"]["toilets"]["count"] == 0,
    ),
    (
        "open_spaces_non_string",
        _set(["floor_plan_analysis", "open_spaces"], [1, {"text": "courtyard"}]),
        lambda d: d["floor_plan_analysis"]["open_spaces"] == ["1", "courtyard"],
    ),
    (
        "center_area_wrong_type",
        _set(["floor_plan_analysis", "center_area"], {"x": 1}),
        lambda d: d["floor_plan_analysis"]["center_area"] is None,
    ),
    (
        "compass_visible_maybe",
        _set(["floor_plan_analysis", "compass_visible"], "maybe"),
        lambda d: d["floor_plan_analysis"]["compass_visible"] is False,
    ),
    (
        "room_analysis_room_null",
        _set(["room_analysis", 0, "room"], None),
        lambda d: d["room_analysis"][0]["room"] == "Unknown",
    ),
    (
        "room_analysis_status_null",
        _set(["room_analysis", 0, "status"], None),
        lambda d: d["room_analysis"][0]["status"] == "neutral",
    ),
    (
        "room_analysis_analysis_null",
        _set(["room_analysis", 0, "analysis"], None),
        lambda d: d["room_analysis"][0]["analysis"] == "",
    ),
    (
        "defect_issue_null",
        _set(["major_defects", 0, "issue"], None),
        lambda d: d["major_defects"][0]["issue"] == "Unknown issue",
    ),
    (
        "defect_impact_null",
        _set(["major_defects", 0, "impact"], None),
        lambda d: d["major_defects"][0]["impact"] == "",
    ),
    (
        "defect_severity_unknown",
        _set(["major_defects", 0, "severity"], "urgent"),
        lambda d: d["major_defects"][0]["severity"] == "medium",
    ),
    (
        "remedy_problem_null",
        _set(["remedies", 0, "problem"], None),
        lambda d: d["remedies"][0]["problem"] == "Unknown problem",
    ),
    (
        "remedy_solution_null",
        _set(["remedies", 0, "solution"], None),
        lambda d: d["remedies"][0]["solution"] == "",
    ),
    (
        "score_explanation_null",
        _set(["score_explanation"], None),
        lambda d: d["score_explanation"] == "",
    ),
    (
        "disclaimer_null",
        _set(["disclaimer"], None),
        lambda d: d["disclaimer"] == DEFAULT_DISCLAIMER,
    ),
    (
        "disclaimer_missing",
        _drop(["disclaimer"]),
        lambda d: d["disclaimer"] == DEFAULT_DISCLAIMER,
    ),
    (
        "vastu_score_null",
        _set(["vastu_score"], None),
        lambda d: d["vastu_score"] == 5,
    ),
    (
        "vastu_score_out_of_range",
        _set(["vastu_score"], 42),
        lambda d: d["vastu_score"] == 10,
    ),
    (
        "assumptions_null",
        _set(["assumptions"], None),
        lambda d: d["assumptions"] == [],
    ),
    (
        "is_valid_floor_plan_maybe",
        _set(["is_valid_floor_plan"], "maybe"),
        lambda d: d["is_valid_floor_plan"] is True,
    ),
    (
        "is_valid_floor_plan_no",
        _set(["is_valid_floor_plan"], "no"),
        lambda d: d["is_valid_floor_plan"] is False,
    ),
    (
        "warning_message_null",
        _set(
            ["analysis_warnings"],
            [{"type": "partial_analysis", "severity": "info", "message": None}],
        ),
        lambda d: any(w["message"] == "Analysis limitation detected" for w in d["warnings"]),
    ),
]


def _png_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(200, 100, 50)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize(("case_id", "mutate", "check"), CASES, ids=[c[0] for c in CASES])
async def test_vastu_field_default_returns_200(
    client: AsyncClient,
    case_id: str,
    mutate: Callable[[dict], None],
    check: Callable[[dict], bool],
):
    payload = copy.deepcopy(BASE_PAYLOAD)
    mutate(payload)
    with patch(
        "app.services.ai.vastu.analyzer._attempt_analysis",
        new=AsyncMock(return_value=payload),
    ):
        response = await client.post(
            "/api/v1/vastu/analyze",
            files={"image": ("plan.png", BytesIO(_png_bytes()), "image/png")},
            data={"north_direction": "up"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert check(body["data"]), body["data"]


@pytest.mark.asyncio
async def test_unusable_provider_output_is_502_envelope(client: AsyncClient):
    """No provider result at all is unusable output: 502 with the shared envelope."""
    with patch(
        "app.services.ai.vastu.analyzer._attempt_analysis",
        new=AsyncMock(return_value=None),
    ):
        response = await client.post(
            "/api/v1/vastu/analyze",
            files={"image": ("plan.png", BytesIO(_png_bytes()), "image/png")},
            data={"north_direction": "up"},
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "VASTU_UNUSABLE_OUTPUT"


@pytest.mark.asyncio
async def test_analyzed_at_is_utc_with_z(client: AsyncClient):
    with patch(
        "app.services.ai.vastu.analyzer._attempt_analysis",
        new=AsyncMock(return_value=copy.deepcopy(BASE_PAYLOAD)),
    ):
        response = await client.post(
            "/api/v1/vastu/analyze",
            files={"image": ("plan.png", BytesIO(_png_bytes()), "image/png")},
            data={"north_direction": "up"},
        )

    assert response.status_code == 200
    analyzed_at = response.json()["analyzed_at"]
    assert analyzed_at.endswith("Z"), analyzed_at
    assert "+00:00" not in analyzed_at
