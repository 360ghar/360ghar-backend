"""
Vastu Analysis Service.

This module provides the main analysis function that uses the AI provider abstraction
to analyze floor plan images for Vastu Shastra compliance.

Robustness features:
- Automatic retries at the HTTP layer via ``AIProvider._make_request`` (tenacity)
- Provider fallback: if the primary provider fails, the secondary provider is tried
- JSON parse retry: if the LLM returns unparseable JSON, one retry with a corrective nudge
"""

from __future__ import annotations

from app.core.constants import (
    DEFAULT_VISION_PROVIDER,
    VALID_VISION_PROVIDERS,
    VASTU_FALLBACK_PROVIDER,
)
from app.core.logging import get_logger
from app.core.utils import utc_now_iso
from app.services.ai import (
    AIMessage,
    AIProviderError,
    AIProviderType,
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
)

logger = get_logger(__name__)

# Nudge appended when the first LLM response fails JSON parsing
_JSON_RETRY_NUDGE = (
    "\n\nIMPORTANT: Your previous response was not valid JSON. "
    "You MUST respond with ONLY a valid JSON object matching the specified format. "
    "Do not include any text before or after the JSON object. "
    "Do not wrap it in markdown code fences."
)


def _get_fallback_provider(primary: str) -> str | None:
    """Return the fallback provider name given the primary, or None if unavailable."""
    # Explicitly configured fallback takes priority
    if VASTU_FALLBACK_PROVIDER and VASTU_FALLBACK_PROVIDER != primary:
        return str(VASTU_FALLBACK_PROVIDER)

    # Default logic: swap between the two supported providers
    for candidate in VALID_VISION_PROVIDERS:
        if candidate != primary:
            return str(candidate)
    return None


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
        return dict(await provider.complete_json(
            messages=messages,
            vision_input=vision_input,
        ))
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

        return dict(await provider.complete_json(
            messages=nudged_messages,
            vision_input=vision_input,
        ))


async def analyze_vastu(
    image_base64: str,
    mime_type: str,
    request: VastuAnalyzeRequest,
) -> VastuAnalyzeResponse:
    """
    Analyze a floor plan image for Vastu compliance.

    Uses the primary AI provider with automatic retries and provider fallback
    to ensure analysis completes successfully whenever possible.

    Args:
        image_base64: Base64-encoded floor plan image
        mime_type: Image MIME type (image/jpeg, image/png, image/webp)
        request: Analysis request with north direction, notes, and provider preference

    Returns:
        VastuAnalyzeResponse with structured analysis and markdown report
    """
    primary_name = request.provider or DEFAULT_VISION_PROVIDER
    analyzed_at = utc_now_iso()

    try:
        provider_type = AIProviderType(primary_name.lower())
    except ValueError:
        logger.warning(
            "Unknown provider '%s', falling back to %s",
            primary_name, DEFAULT_VISION_PROVIDER,
        )
        provider_type = AIProviderType(DEFAULT_VISION_PROVIDER)
        primary_name = DEFAULT_VISION_PROVIDER

    # Resolve fallback provider once
    fallback_name = _get_fallback_provider(primary_name)

    # Build messages and vision input (shared across attempts)
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

    # --- Attempt with primary provider ---
    result_json = await _attempt_analysis(
        primary_name, provider_type, messages, vision_input, analyzed_at,
    )

    # --- Fallback to secondary provider if primary failed ---
    if result_json is None and fallback_name:
        logger.warning(
            "Primary provider '%s' failed; falling back to '%s'",
            primary_name, fallback_name,
        )
        try:
            fallback_type = AIProviderType(fallback_name.lower())
        except ValueError:
            logger.error("Fallback provider '%s' is invalid", fallback_name)
            return VastuAnalyzeResponse(
                success=False,
                error=f"Primary provider '{primary_name}' failed and fallback '{fallback_name}' is invalid",
                provider_used=primary_name,
                analyzed_at=analyzed_at,
            )

        result_json = await _attempt_analysis(
            fallback_name, fallback_type, messages, vision_input, analyzed_at,
            provider_used_label=f"{primary_name} -> {fallback_name}",
        )

    # --- Both providers failed ---
    if result_json is None:
        return VastuAnalyzeResponse(
            success=False,
            error=f"Analysis failed with primary provider '{primary_name}'"
                  + (f" and fallback provider '{fallback_name}'" if fallback_name else ""),
            provider_used=primary_name,
            analyzed_at=analyzed_at,
        )

    # --- Build success response ---
    provider_used_label = result_json.pop("_provider_used", primary_name)

    analysis_result = _parse_analysis_result(result_json)
    report_markdown = generate_markdown_report(result_json)

    has_warnings = len(analysis_result.warnings) > 0
    warning_count = len(analysis_result.warnings)
    critical_warnings = any(
        w.severity == AnalysisWarningSeverity.CRITICAL
        for w in analysis_result.warnings
    )

    return VastuAnalyzeResponse(
        success=True,
        data=analysis_result,
        report_markdown=report_markdown,
        has_warnings=has_warnings,
        warning_count=warning_count,
        critical_warnings=critical_warnings,
        provider_used=provider_used_label,
        analyzed_at=analyzed_at,
    )


async def _attempt_analysis(
    provider_name: str,
    provider_type: AIProviderType,
    messages: list[AIMessage],
    vision_input: VisionInput,
    analyzed_at: str,
    provider_used_label: str | None = None,
) -> dict | None:
    """
    Try to get a Vastu analysis from a single provider.

    Returns the raw JSON dict on success (with ``_provider_used`` key injected),
    or None on failure.
    """
    try:
        provider = get_ai_provider(provider_type)

        if not provider.supports_vision:
            logger.warning("Provider %s does not support vision; skipping", provider_name)
            return None

        logger.info("Starting Vastu analysis with provider: %s", provider_name)

        result_json = await _call_provider_with_json_retry(
            provider, messages, vision_input,
        )

        logger.info("Vastu analysis completed successfully with provider: %s", provider_name)
        result_json["_provider_used"] = provider_used_label or provider_name
        return result_json

    except AIProviderError as e:
        logger.error("AI provider error with %s: %s", provider_name, e)
        return None
    except ValueError as e:
        logger.error("Validation error with %s: %s", provider_name, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error with provider %s: %s", provider_name, e)
        return None


def _parse_analysis_result(result_json: dict) -> VastuAnalysisResult:
    """
    Parse and validate the raw JSON result into a VastuAnalysisResult.

    Handles partial data gracefully with defaults.
    """
    # Parse floor plan analysis
    fp_data = result_json.get("floor_plan_analysis", {})

    rooms = []
    for room in fp_data.get("rooms", []):
        rooms.append(RoomInfo(
            name=room.get("name", "Unknown"),
            direction=room.get("direction", "Unknown"),
            notes=room.get("notes"),
        ))

    entrance = None
    if fp_data.get("entrance"):
        entrance = EntranceInfo(
            direction=fp_data["entrance"].get("direction", "Unknown"),
            type=fp_data["entrance"].get("type"),
        )

    toilets = None
    if fp_data.get("toilets"):
        toilets = ToiletInfo(
            count=fp_data["toilets"].get("count", 0),
            directions=fp_data["toilets"].get("directions", []),
        )

    staircase = None
    if fp_data.get("staircase"):
        staircase = StaircaseInfo(
            direction=fp_data["staircase"].get("direction", "Unknown"),
            type=fp_data["staircase"].get("type"),
        )

    balconies = None
    if fp_data.get("balconies"):
        balconies = BalconyInfo(
            count=fp_data["balconies"].get("count", 0),
            directions=fp_data["balconies"].get("directions", []),
        )

    floor_plan = FloorPlanAnalysis(
        plot_shape=fp_data.get("plot_shape"),
        rooms=rooms,
        entrance=entrance,
        kitchen=fp_data.get("kitchen"),
        toilets=toilets,
        staircase=staircase,
        balconies=balconies,
        open_spaces=fp_data.get("open_spaces"),
        center_area=fp_data.get("center_area"),
        compass_visible=fp_data.get("compass_visible", False),
    )

    # Parse room analysis
    room_analysis = []
    for ra in result_json.get("room_analysis", []):
        try:
            status = VastuStatus(ra.get("status", "neutral").lower())
        except ValueError:
            status = VastuStatus.NEUTRAL

        room_analysis.append(RoomVastuAnalysis(
            room=ra.get("room", "Unknown"),
            direction=ra.get("direction", "Unknown"),
            status=status,
            analysis=ra.get("analysis", ""),
        ))

    # Parse major defects
    major_defects = []
    for defect in result_json.get("major_defects", [])[:5]:  # Limit to 5
        try:
            severity = DefectSeverity(defect.get("severity", "medium").lower())
        except ValueError:
            severity = DefectSeverity.MEDIUM

        major_defects.append(VastuDefect(
            issue=defect.get("issue", "Unknown issue"),
            severity=severity,
            impact=defect.get("impact", ""),
        ))

    # Parse remedies
    remedies = []
    for remedy in result_json.get("remedies", []):
        try:
            remedy_type = RemedyType(remedy.get("type", "placement").lower())
        except ValueError:
            remedy_type = RemedyType.PLACEMENT

        remedies.append(VastuRemedy(
            problem=remedy.get("problem", "Unknown problem"),
            solution=remedy.get("solution", ""),
            type=remedy_type,
        ))

    # Clamp score to 1-10 range
    score = result_json.get("vastu_score", 5)
    score = max(1, min(10, round(score)))

    # Generate warnings based on analysis
    warnings, confidence = _generate_analysis_warnings(result_json, floor_plan, rooms)

    # Determine if this is a valid floor plan
    is_valid = result_json.get("is_valid_floor_plan", True)

    return VastuAnalysisResult(
        floor_plan_analysis=floor_plan,
        vastu_score=score,
        score_explanation=result_json.get("score_explanation", ""),
        assumptions=result_json.get("assumptions", []),
        room_analysis=room_analysis,
        major_defects=major_defects,
        remedies=remedies,
        improvements=result_json.get("improvements", []),
        disclaimer=result_json.get(
            "disclaimer",
            "This analysis is based on traditional Vastu Shastra principles and the floor plan information provided. "
            "Individual results may vary. For major structural changes, consult a qualified Vastu expert in person. "
            "This is for informational purposes only."
        ),
        analysis_confidence=confidence,
        warnings=warnings,
        is_valid_floor_plan=is_valid,
    )


def _generate_analysis_warnings(
    result_json: dict,
    floor_plan: FloorPlanAnalysis,
    rooms: list
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
        warnings.append(AnalysisWarning(
            type=AnalysisWarningType.NOT_FLOOR_PLAN,
            severity=AnalysisWarningSeverity.CRITICAL,
            message="This image does not appear to be a floor plan. The analysis may not be accurate.",
            suggestion="Please upload a clear 2D floor plan showing room layouts, walls, and doors. Avoid photographs, 3D renders, or decorative images."
        ))
        confidence = min(confidence, 0.3)

    # Get room names for checking
    room_names_lower = [r.name.lower() for r in rooms]

    # Missing kitchen
    has_kitchen = (
        any("kitchen" in name for name in room_names_lower) or
        floor_plan.kitchen is not None
    )
    if not has_kitchen and result_json.get("is_valid_floor_plan", True):
        warnings.append(AnalysisWarning(
            type=AnalysisWarningType.MISSING_KITCHEN,
            severity=AnalysisWarningSeverity.WARNING,
            message="No kitchen was detected in the floor plan.",
            suggestion="If your floor plan includes a kitchen, ensure it is clearly labeled or distinguishable. Kitchen placement is crucial for Vastu analysis."
        ))
        confidence = min(confidence, 0.8)

    # Missing bedroom
    has_bedroom = any(
        "bedroom" in name or "bed room" in name or "master" in name
        for name in room_names_lower
    )
    if not has_bedroom and result_json.get("is_valid_floor_plan", True):
        warnings.append(AnalysisWarning(
            type=AnalysisWarningType.MISSING_BEDROOM,
            severity=AnalysisWarningSeverity.WARNING,
            message="No bedroom was detected in the floor plan.",
            suggestion="If your floor plan includes bedrooms, ensure they are labeled. Bedroom placement affects rest and relationships in Vastu."
        ))
        confidence = min(confidence, 0.8)

    # Missing bathroom
    has_bathroom = (
        any("bath" in name or "toilet" in name or "wc" in name or "washroom" in name
            for name in room_names_lower) or
        (floor_plan.toilets is not None and floor_plan.toilets.count > 0)
    )
    if not has_bathroom and result_json.get("is_valid_floor_plan", True):
        warnings.append(AnalysisWarning(
            type=AnalysisWarningType.MISSING_BATHROOM,
            severity=AnalysisWarningSeverity.WARNING,
            message="No bathroom or toilet was detected in the floor plan.",
            suggestion="If your floor plan includes bathrooms, ensure they are marked. Toilet placement is important in Vastu."
        ))
        confidence = min(confidence, 0.85)

    # Missing entrance
    if floor_plan.entrance is None and result_json.get("is_valid_floor_plan", True):
        warnings.append(AnalysisWarning(
            type=AnalysisWarningType.MISSING_ENTRANCE,
            severity=AnalysisWarningSeverity.WARNING,
            message="The main entrance could not be identified.",
            suggestion="The main door is crucial for Vastu analysis. Please ensure it is visible and marked in your floor plan."
        ))
        confidence = min(confidence, 0.7)

    # Very few rooms detected
    if len(rooms) < 3 and result_json.get("is_valid_floor_plan", True):
        warnings.append(AnalysisWarning(
            type=AnalysisWarningType.FEW_ROOMS_DETECTED,
            severity=AnalysisWarningSeverity.WARNING,
            message=f"Only {len(rooms)} room(s) were detected, which seems unusually low for a complete floor plan.",
            suggestion="If more rooms exist, try uploading a clearer image with better contrast and visible room labels."
        ))
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
                warnings.append(AnalysisWarning(
                    type=warning_type,
                    severity=severity,
                    message=w.get("message", "Analysis limitation detected"),
                    suggestion=w.get("suggestion", "Try uploading a clearer floor plan image.")
                ))
        except Exception:
            # Skip invalid warnings
            pass

    return warnings, confidence
