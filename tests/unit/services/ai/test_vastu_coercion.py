"""Vastu LLM output is coerced into the result model; unusable output is a 502."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import ExternalServiceError
from app.services.ai.vastu import analyzer
from app.services.ai.vastu.schemas import VastuAnalyzeRequest


def _drifted_llm_output() -> dict:
    """Shapes the model returns in practice: null lists, numbers as strings, string sections."""
    return {
        "floor_plan_analysis": {
            "rooms": [{"name": None, "direction": 5, "notes": None}, "not-a-room"],
            "entrance": "North-East",
            "kitchen": 3,
            "toilets": {"count": None, "directions": None},
            "staircase": None,
            "balconies": "south",
        },
        "vastu_score": "seven",
        "improvements": None,
        "assumptions": None,
    }


def test_coerce_turns_drifted_output_into_a_parsable_result():
    coerced = analyzer._coerce_analysis_input(_drifted_llm_output())

    result = analyzer._parse_analysis_result(coerced)

    assert result.vastu_score == 5  # non-numeric score falls back to the default
    assert [room.name for room in result.floor_plan_analysis.rooms] == ["Unknown"]
    assert result.floor_plan_analysis.entrance.direction == "North-East"
    assert result.floor_plan_analysis.kitchen == {"description": "3"}
    assert result.floor_plan_analysis.toilets.count == 0
    assert result.floor_plan_analysis.toilets.directions == []


def test_coerce_clamps_score_and_handles_non_dict_root_sections():
    coerced = analyzer._coerce_analysis_input({"floor_plan_analysis": "oops", "vastu_score": 42})

    assert coerced["vastu_score"] == 10
    assert coerced["floor_plan_analysis"]["rooms"] == []
    assert coerced["floor_plan_analysis"]["entrance"] is None


@pytest.mark.asyncio
async def test_analyze_vastu_provider_without_result_raises_502():
    request = VastuAnalyzeRequest(north_direction="up", notes=None)
    with patch.object(analyzer, "_attempt_analysis", new=AsyncMock(return_value=None)):
        with pytest.raises(ExternalServiceError) as exc:
            await analyzer.analyze_vastu("aW1n", "image/png", request)

    assert exc.value.status_code == 502
    assert exc.value.error_code == "VASTU_UNUSABLE_OUTPUT"


@pytest.mark.asyncio
async def test_analyze_vastu_parser_crash_is_502_not_500():
    request = VastuAnalyzeRequest(north_direction="up", notes=None)
    with (
        patch.object(
            analyzer, "_attempt_analysis", new=AsyncMock(return_value={"floor_plan_analysis": {}})
        ),
        patch.object(analyzer, "_parse_analysis_result", side_effect=TypeError("boom")),
    ):
        with pytest.raises(ExternalServiceError) as exc:
            await analyzer.analyze_vastu("aW1n", "image/png", request)

    assert exc.value.status_code == 502
    assert "boom" not in exc.value.detail


def test_unknown_labels_get_the_parser_defaults_before_the_report_is_built():
    raw = {
        "room_analysis": [
            {"room": "Kitchen", "direction": "SE", "status": "Placement|Element", "analysis": "x"}
        ],
        "remedies": [{"problem": "p", "solution": "s", "type": "Placement|Element"}],
        "major_defects": [{"issue": "i", "severity": "bogus", "impact": ""}],
        "vastu_score": 6,
    }

    coerced = analyzer._coerce_analysis_input(raw)
    result = analyzer._parse_analysis_result(coerced)

    assert coerced["room_analysis"][0]["status"] == "neutral"
    assert coerced["remedies"][0]["type"] == "placement"
    assert coerced["major_defects"][0]["severity"] == "medium"
    assert result.room_analysis[0].status == "neutral"
    assert result.remedies[0].type == "placement"


@pytest.mark.asyncio
async def test_report_markdown_matches_the_structured_labels():
    raw = {
        "room_analysis": [{"room": "Kitchen", "direction": "SE", "status": "Problematic"}],
        "remedies": [{"problem": "p", "solution": "s", "type": "Placement|Element"}],
        "vastu_score": 6,
    }
    request = VastuAnalyzeRequest(north_direction="up", notes=None)
    with patch.object(analyzer, "_attempt_analysis", new=AsyncMock(return_value=raw)):
        response = await analyzer.analyze_vastu("aW1n", "image/png", request)

    assert response.data.room_analysis[0].status == "problematic"
    assert "Placement|Element" not in response.report_markdown
    assert "Problematic" in response.report_markdown or "problematic" in response.report_markdown
