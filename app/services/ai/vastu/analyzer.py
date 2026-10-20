"""
Vastu Analysis Service.

This module provides the main analysis function that uses the AI provider abstraction
to analyze floor plan images for Vastu Shastra compliance.

Robustness features:
- Automatic retries at the HTTP layer via ``AIProvider._make_request`` (tenacity)
- JSON parse retry: if the LLM returns unparseable JSON, one retry with a corrective nudge
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from app.core.constants import DEFAULT_VISION_PROVIDER
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger
from app.core.utils import utc_now
from app.services.ai import (
    AIMessage,
    AIProviderError,
    AIRole,
    VisionInput,
    get_ai_provider,
)
from app.services.ai.vastu.prompts import (
    VASTU_VISION_SYSTEM_PROMPT,
    generate_markdown_report,
    get_user_prompt,
)
from app.services.ai.vastu.schemas import (
    AnalysisWarning,
    AnalysisWarningSeverity,
    AnalysisWarningType,
    BalconyInfo,
    DefectSeverity,
    EntranceInfo,
    FloorPlanAnalysis,
    RemedyType,
    RoomInfo,
    RoomVastuAnalysis,
    StaircaseInfo,
    ToiletInfo,
    VastuAnalysisResult,
    VastuAnalyzeRequest,
    VastuAnalyzeResponse,
    VastuDefect,
    VastuRemedy,
    VastuStatus,
    coerce_string_list,
)

logger = get_logger(__name__)

# Nudge appended when the first LLM response fails JSON parsing
_JSON_RETRY_NUDGE = (
    "\n\nIMPORTANT: Your previous response was not valid JSON. "
    "You MUST respond with ONLY a valid JSON object matching the specified format. "
    "Do not include any text before or after the JSON object. "
    "Do not wrap it in markdown code fences."
)


async def _call_provider_with_json_retry(
    provider,
    messages: list[AIMessage],
    vision_input: VisionInput,
) -> dict:
    """
    Call provider.complete_json() with one JSON-parse retry.

    If the first call succeeds but returns unparseable JSON, retry once
    with a corrective nudge appended to the last user message.
    """
    try:
        return dict(
            await provider.complete_json(
                messages=messages,
                vision_input=vision_input,
            )
        )
    except AIProviderError as exc:
        # Only retry on JSON parse failures, not on HTTP/auth errors
        if "Failed to parse JSON" not in str(exc):
            raise

        logger.warning("JSON parse failed on first attempt; retrying with corrective nudge")

        # Build nudged messages: append the nudge to the last user message
        nudged_messages = list(messages)
        last_idx = len(nudged_messages) - 1
        if last_idx >= 0 and nudged_messages[last_idx].role == AIRole.USER:
            original = nudged_messages[last_idx]
            nudged_messages[last_idx] = AIMessage(
                role=AIRole.USER,
                content=original.content + _JSON_RETRY_NUDGE,
            )

        return dict(
            await provider.complete_json(
                messages=nudged_messages,
                vision_input=vision_input,
            )
        )


async def analyze_vastu(
    image_base64: str,
    mime_type: str,
    request: VastuAnalyzeRequest,
) -> VastuAnalyzeResponse:
    """
    Analyze a floor plan image for Vastu compliance.

    Uses the Agnes AI provider with automatic HTTP retries.

    Args:
        image_base64: Base64-encoded floor plan image
        mime_type: Image MIME type (image/jpeg, image/png, image/webp)
        request: Analysis request with north direction and notes

    Returns:
        VastuAnalyzeResponse with structured analysis and markdown report
    """
    provider_used = DEFAULT_VISION_PROVIDER
    analyzed_at = utc_now()

    messages = [
        AIMessage(role=AIRole.SYSTEM, content=VASTU_VISION_SYSTEM_PROMPT),
        AIMessage(
            role=AIRole.USER,
            content=get_user_prompt(request.north_direction.value, request.notes or ""),
        ),
    ]
    vision_input = VisionInput(
        image_base64=image_base64,
        mime_type=mime_type,
    )

    result_json = await _attempt_analysis(messages, vision_input)
    if result_json is None:
        raise unusable_analysis_error("the provider returned no result")

    try:
        # Coerce the LLM output into the shape the parser expects. Anything
        # that still fails below is an unusable result, not a server crash.
        normalized = _coerce_analysis_input(result_json)
        analysis_result = _parse_analysis_result(normalized)
        report_markdown = generate_markdown_report(normalized)
    except Exception as exc:
        logger.error("Vastu result could not be parsed: %s", exc, exc_info=True)
        raise unusable_analysis_error("the result could not be parsed") from exc

    has_warnings = len(analysis_result.warnings) > 0
    warning_count = len(analysis_result.warnings)
    critical_warnings = any(
        w.severity == AnalysisWarningSeverity.CRITICAL for w in analysis_result.warnings
    )

    return VastuAnalyzeResponse(
        data=analysis_result,
        report_markdown=report_markdown,
        has_warnings=has_warnings,
        warning_count=warning_count,
        critical_warnings=critical_warnings,
        provider_used=provider_used,
        analyzed_at=analyzed_at,
    )


VASTU_UNUSABLE_MESSAGE = "The analysis service returned an unusable result. Please try again."


def unusable_analysis_error(reason: str) -> ExternalServiceError:
    """A 502 with the shared envelope. The reason is logged, never returned."""
    logger.warning("Vastu analysis unusable: %s", reason)
    return ExternalServiceError(VASTU_UNUSABLE_MESSAGE, error_code="VASTU_UNUSABLE_OUTPUT")


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_text(value: object, default: str | None = None) -> str | None:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return default


def _as_count(value: object, default: int = 0) -> int:
    try:
        return max(0, int(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_score(value: object, default: int = 5) -> int:
    try:
        return max(1, min(10, round(float(value))))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _coerce_section(value: object) -> dict[str, Any] | None:
    """A floor-plan section (entrance, toilets, ...). A bare string becomes its direction."""
    if isinstance(value, str):
        return {"direction": value}
    if isinstance(value, dict):
        return value
    return None


def _enum_value(enum_cls: type[Enum], raw: object, default: Enum) -> str:
    """The enum value for a raw LLM label, or the default when the label is unknown."""
    try:
        return str(enum_cls(str(raw).lower()).value)
    except ValueError:
        return str(default.value)


_TRUE_TEXT = frozenset({"true", "yes", "y", "1"})
_FALSE_TEXT = frozenset({"false", "no", "n", "0"})
DEFAULT_DISCLAIMER = (
    "This analysis is based on traditional Vastu Shastra principles and the floor plan "
    "information provided. Individual results may vary. For major structural changes, "
    "consult a qualified Vastu expert in person. This is for informational purposes only."
)


def _as_bool(value: object, default: bool) -> bool:
    """A bool from an LLM value. Any other text, such as 'maybe', is the default."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE_TEXT:
            return True
        if text in _FALSE_TEXT:
            return False
    return default


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _coerce_analysis_input(raw: dict[str, Any]) -> dict[str, Any]:
    """Shape the raw LLM dict into the exact types the result model reads.

    Every field that the result model requires gets a value of the right type,
    or the documented default. Null, a wrong type, or an unknown label never
    reaches the model. The markdown report and the structured result both read
    this output, so they agree. Running it twice gives the same result.
    """
    fp = _as_dict(raw.get("floor_plan_analysis"))

    rooms: list[dict[str, Any]] = [
        {
            "name": _as_text(room.get("name"), "Unknown"),
            "direction": _as_text(room.get("direction"), "Unknown"),
            "notes": _as_text(room.get("notes")),
        }
        for room in _as_list(fp.get("rooms"))
        if isinstance(room, dict)
    ]

    entrance_raw = _coerce_section(fp.get("entrance"))
    entrance = None
    if entrance_raw is not None:
        entrance = {
            "direction": _as_text(entrance_raw.get("direction"), "Unknown"),
            "type": _as_text(entrance_raw.get("type")),
        }

    kitchen_raw = fp.get("kitchen")
    kitchen: dict[str, str] | None = None
    if isinstance(kitchen_raw, dict):
        kitchen = {str(k): _as_text(v, "") or "" for k, v in kitchen_raw.items() if v is not None}
    elif kitchen_raw is not None:
        kitchen = {"description": str(kitchen_raw)}

    toilets_raw = _coerce_section(fp.get("toilets"))
    toilets = None
    if toilets_raw is not None:
        toilets = {
            "count": _as_count(toilets_raw.get("count")),
            "directions": coerce_string_list(toilets_raw.get("directions")),
        }
    balconies_raw = _coerce_section(fp.get("balconies"))
    balconies = None
    if balconies_raw is not None:
        balconies = {
            "count": _as_count(balconies_raw.get("count")),
            "directions": coerce_string_list(balconies_raw.get("directions")),
        }
    staircase_raw = _coerce_section(fp.get("staircase"))
    staircase = None
    if staircase_raw is not None:
        staircase = {
            "direction": _as_text(staircase_raw.get("direction"), "Unknown"),
            "type": _as_text(staircase_raw.get("type")),
        }

    open_spaces = fp.get("open_spaces")
    room_analysis = [
        {
            "room": _as_text(ra.get("room"), "Unknown"),
            "direction": _as_text(ra.get("direction"), "Unknown"),
            "status": _enum_value(VastuStatus, ra.get("status"), VastuStatus.NEUTRAL),
            "analysis": _as_text(ra.get("analysis"), ""),
        }
        for ra in _as_list(raw.get("room_analysis"))
        if isinstance(ra, dict)
    ]
    major_defects = [
        {
            "issue": _as_text(defect.get("issue"), "Unknown issue"),
            "severity": _enum_value(DefectSeverity, defect.get("severity"), DefectSeverity.MEDIUM),
            "impact": _as_text(defect.get("impact"), ""),
        }
        for defect in _as_list(raw.get("major_defects"))
        if isinstance(defect, dict)
    ][:5]
    remedies = [
        {
            "problem": _as_text(remedy.get("problem"), "Unknown problem"),
            "solution": _as_text(remedy.get("solution"), ""),
            "type": _enum_value(RemedyType, remedy.get("type"), RemedyType.PLACEMENT),
        }
        for remedy in _as_list(raw.get("remedies"))
        if isinstance(remedy, dict)
    ]
    analysis_warnings = [
        {
            "type": _as_text(w.get("type"), "partial_analysis"),
            "severity": _as_text(w.get("severity"), "info"),
            "message": _as_text(w.get("message")) or "Analysis limitation detected",
            "suggestion": _as_text(w.get("suggestion"))
            or "Try uploading a clearer floor plan image.",
        }
        for w in _as_list(raw.get("analysis_warnings"))
        if isinstance(w, dict)
    ]

    data = dict(raw)
    data.update(
        {
            "floor_plan_analysis": {
                "plot_shape": _as_text(fp.get("plot_shape")),
                "rooms": rooms,
                "entrance": entrance,
                "kitchen": kitchen,
                "toilets": toilets,
                "balconies": balconies,
                "staircase": staircase,
                "open_spaces": None if open_spaces is None else coerce_string_list(open_spaces),
                "center_area": _as_text(fp.get("center_area")),
                "compass_visible": _as_bool(fp.get("compass_visible"), False),
            },
            "room_analysis": room_analysis,
            "major_defects": major_defects,
            "remedies": remedies,
            "analysis_warnings": analysis_warnings,
            "vastu_score": _as_score(raw.get("vastu_score")),
            "score_explanation": _as_text(raw.get("score_explanation"), "") or "",
            "assumptions": coerce_string_list(raw.get("assumptions")),
            "improvements": coerce_string_list(raw.get("improvements")),
            "disclaimer": _as_text(raw.get("disclaimer")) or DEFAULT_DISCLAIMER,
            "is_valid_floor_plan": _as_bool(raw.get("is_valid_floor_plan"), True),
        }
    )
    return data


async def _attempt_analysis(
    messages: list[AIMessage],
    vision_input: VisionInput,
) -> dict | None:
    """Get a raw Vastu analysis JSON dict from Agnes AI, or None on failure."""
    try:
        provider = get_ai_provider()
        return await _call_provider_with_json_retry(provider, messages, vision_input)
    except AIProviderError as e:
        logger.error("AI provider error with %s: %s", DEFAULT_VISION_PROVIDER, e)
        return None
    except ValueError as e:
        logger.error("Validation error with %s: %s", DEFAULT_VISION_PROVIDER, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error with provider %s: %s", DEFAULT_VISION_PROVIDER, e)
        return None


def _parse_analysis_result(result_json: dict) -> VastuAnalysisResult:
    """Build the result model from LLM JSON. Coercion runs first, so defaults apply."""
    data = _coerce_analysis_input(result_json)
    fp = data["floor_plan_analysis"]

    rooms = [RoomInfo.model_validate(room) for room in fp["rooms"]]
    floor_plan = FloorPlanAnalysis(
        plot_shape=fp["plot_shape"],
        rooms=rooms,
        entrance=EntranceInfo.model_validate(fp["entrance"]) if fp["entrance"] else None,
        kitchen=fp["kitchen"],
        toilets=ToiletInfo.model_validate(fp["toilets"]) if fp["toilets"] else None,
        staircase=StaircaseInfo.model_validate(fp["staircase"]) if fp["staircase"] else None,
        balconies=BalconyInfo.model_validate(fp["balconies"]) if fp["balconies"] else None,
        open_spaces=fp["open_spaces"],
        center_area=fp["center_area"],
        compass_visible=fp["compass_visible"],
    )
    room_analysis = [RoomVastuAnalysis.model_validate(ra) for ra in data["room_analysis"]]
    major_defects = [VastuDefect.model_validate(d) for d in data["major_defects"]]
    remedies = [VastuRemedy.model_validate(r) for r in data["remedies"]]

    warnings, confidence = _generate_analysis_warnings(data, floor_plan, rooms)

    return VastuAnalysisResult(
        floor_plan_analysis=floor_plan,
        vastu_score=data["vastu_score"],
        score_explanation=data["score_explanation"],
        assumptions=data["assumptions"],
        room_analysis=room_analysis,
        major_defects=major_defects,
        remedies=remedies,
        improvements=data["improvements"],
        disclaimer=data["disclaimer"],
        analysis_confidence=confidence,
        warnings=warnings,
        is_valid_floor_plan=data["is_valid_floor_plan"],
    )


def _generate_analysis_warnings(
    result_json: dict, floor_plan: FloorPlanAnalysis, rooms: list
) -> tuple[list[AnalysisWarning], float]:
    """
    Analyze the result and generate appropriate warnings.

    Returns:
        Tuple of (warnings list, adjusted confidence score)
    """
    warnings = []
    confidence = result_json.get("analysis_confidence", 1.0)

    # Ensure confidence is a valid float
    try:
        confidence = float(confidence)
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 1.0

    # Check if it's a valid floor plan
    if not result_json.get("is_valid_floor_plan", True):
        warnings.append(
            AnalysisWarning(
                type=AnalysisWarningType.NOT_FLOOR_PLAN,
                severity=AnalysisWarningSeverity.CRITICAL,
                message="This image does not appear to be a floor plan. The analysis may not be accurate.",
                suggestion="Please upload a clear 2D floor plan showing room layouts, walls, and doors. Avoid photographs, 3D renders, or decorative images.",
            )
        )
        confidence = min(confidence, 0.3)

    # Get room names for checking
    room_names_lower = [r.name.lower() for r in rooms]

    # Missing kitchen
    has_kitchen = (
        any("kitchen" in name for name in room_names_lower) or floor_plan.kitchen is not None
    )
    if not has_kitchen and result_json.get("is_valid_floor_plan", True):
        warnings.append(
            AnalysisWarning(
                type=AnalysisWarningType.MISSING_KITCHEN,
                severity=AnalysisWarningSeverity.WARNING,
                message="No kitchen was detected in the floor plan.",
                suggestion="If your floor plan includes a kitchen, ensure it is clearly labeled or distinguishable. Kitchen placement is crucial for Vastu analysis.",
            )
        )
        confidence = min(confidence, 0.8)

    # Missing bedroom
    has_bedroom = any(
        "bedroom" in name or "bed room" in name or "master" in name for name in room_names_lower
    )
    if not has_bedroom and result_json.get("is_valid_floor_plan", True):
        warnings.append(
            AnalysisWarning(
                type=AnalysisWarningType.MISSING_BEDROOM,
                severity=AnalysisWarningSeverity.WARNING,
                message="No bedroom was detected in the floor plan.",
                suggestion="If your floor plan includes bedrooms, ensure they are labeled. Bedroom placement affects rest and relationships in Vastu.",
            )
        )
        confidence = min(confidence, 0.8)

    # Missing bathroom
    has_bathroom = any(
        "bath" in name or "toilet" in name or "wc" in name or "washroom" in name
        for name in room_names_lower
    ) or (floor_plan.toilets is not None and floor_plan.toilets.count > 0)
    if not has_bathroom and result_json.get("is_valid_floor_plan", True):
        warnings.append(
            AnalysisWarning(
                type=AnalysisWarningType.MISSING_BATHROOM,
                severity=AnalysisWarningSeverity.WARNING,
                message="No bathroom or toilet was detected in the floor plan.",
                suggestion="If your floor plan includes bathrooms, ensure they are marked. Toilet placement is important in Vastu.",
            )
        )
        confidence = min(confidence, 0.85)

    # Missing entrance
    if floor_plan.entrance is None and result_json.get("is_valid_floor_plan", True):
        warnings.append(
            AnalysisWarning(
                type=AnalysisWarningType.MISSING_ENTRANCE,
                severity=AnalysisWarningSeverity.WARNING,
                message="The main entrance could not be identified.",
                suggestion="The main door is crucial for Vastu analysis. Please ensure it is visible and marked in your floor plan.",
            )
        )
        confidence = min(confidence, 0.7)

    # Very few rooms detected
    if len(rooms) < 3 and result_json.get("is_valid_floor_plan", True):
        warnings.append(
            AnalysisWarning(
                type=AnalysisWarningType.FEW_ROOMS_DETECTED,
                severity=AnalysisWarningSeverity.WARNING,
                message=f"Only {len(rooms)} room(s) were detected, which seems unusually low for a complete floor plan.",
                suggestion="If more rooms exist, try uploading a clearer image with better contrast and visible room labels.",
            )
        )
        confidence = min(confidence, 0.7)

    # Include AI-generated warnings from response
    ai_warnings = result_json.get("analysis_warnings", [])
    for w in ai_warnings:
        try:
            # Map the warning type string to enum
            warning_type_str = w.get("type", "partial_analysis")
            try:
                warning_type = AnalysisWarningType(warning_type_str)
            except ValueError:
                warning_type = AnalysisWarningType.PARTIAL_ANALYSIS

            # Map severity
            severity_str = w.get("severity", "info")
            try:
                severity = AnalysisWarningSeverity(severity_str)
            except ValueError:
                severity = AnalysisWarningSeverity.INFO

            # Check if this warning type already exists (avoid duplicates)
            existing_types = [existing.type for existing in warnings]
            if warning_type not in existing_types:
                warnings.append(
                    AnalysisWarning(
                        type=warning_type,
                        severity=severity,
                        message=w.get("message", "Analysis limitation detected"),
                        suggestion=w.get("suggestion", "Try uploading a clearer floor plan image."),
                    )
                )
        except Exception:
            # Skip invalid warnings
            pass

    return warnings, confidence
