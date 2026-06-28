"""
Pydantic schemas for Vastu analysis.

These schemas define the request/response structure for the Vastu checker API.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import DEFAULT_VISION_PROVIDER
from app.core.utils import utc_now_iso


class NorthDirection(str, Enum):
    """Direction of North in the floor plan image."""
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    UNKNOWN = "unknown"


class VastuStatus(str, Enum):
    """Status rating for Vastu compliance."""
    EXCELLENT = "excellent"
    GOOD = "good"
    NEUTRAL = "neutral"
    CONCERNING = "concerning"
    PROBLEMATIC = "problematic"


class DefectSeverity(str, Enum):
    """Severity level of a Vastu defect."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RemedyType(str, Enum):
    """Type of Vastu remedy."""
    PLACEMENT = "placement"
    COLOR = "color"
    ELEMENT = "element"
    STRUCTURAL = "structural"


class AnalysisWarningType(str, Enum):
    """Types of warnings that can occur during analysis."""
    NOT_FLOOR_PLAN = "not_floor_plan"
    MISSING_KITCHEN = "missing_kitchen"
    MISSING_BEDROOM = "missing_bedroom"
    MISSING_BATHROOM = "missing_bathroom"
    MISSING_ENTRANCE = "missing_entrance"
    FEW_ROOMS_DETECTED = "few_rooms_detected"
    UNCLEAR_LAYOUT = "unclear_layout"
    LOW_IMAGE_QUALITY = "low_image_quality"
    PARTIAL_ANALYSIS = "partial_analysis"
    AMBIGUOUS_DIRECTIONS = "ambiguous_directions"


class AnalysisWarningSeverity(str, Enum):
    """Severity level of an analysis warning."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# Request Schemas
class VastuAnalyzeRequest(BaseModel):
    """Request payload for Vastu analysis."""
    north_direction: NorthDirection = Field(
        default=NorthDirection.UP,
        description="Direction of North in the floor plan image"
    )
    notes: str | None = Field(
        default=None,
        max_length=1000,
        description="Additional notes or concerns about the property"
    )
    provider: str | None = Field(
        default=DEFAULT_VISION_PROVIDER,
        description="AI provider to use: 'gemini' or 'glm'"
    )


# Response Schemas
class RoomInfo(BaseModel):
    """Information about a room in the floor plan."""
    name: str
    direction: str
    notes: str | None = None


class EntranceInfo(BaseModel):
    """Information about the main entrance."""
    direction: str
    type: str | None = None


def _coerce_count_value(v: object) -> int:
    """Coerce a count value to int, handling string-encoded floats like '2.5'."""
    try:
        return int(float(v))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


class ToiletInfo(BaseModel):
    """Information about toilets/bathrooms."""
    count: int
    directions: list[str]

    @field_validator("count", mode="before")
    @classmethod
    def _coerce_count(cls, v: object) -> int:
        return _coerce_count_value(v)


class StaircaseInfo(BaseModel):
    """Information about staircase."""
    direction: str
    type: str | None = None


class BalconyInfo(BaseModel):
    """Information about balconies."""
    count: int
    directions: list[str]

    @field_validator("count", mode="before")
    @classmethod
    def _coerce_count(cls, v: object) -> int:
        return _coerce_count_value(v)


class FloorPlanAnalysis(BaseModel):
    """Extracted floor plan layout information."""
    plot_shape: str | None = None
    rooms: list[RoomInfo] = []
    entrance: EntranceInfo | None = None
    kitchen: dict[str, str] | None = None
    toilets: ToiletInfo | None = None
    staircase: StaircaseInfo | None = None
    balconies: BalconyInfo | None = None
    open_spaces: list[str] | None = None
    center_area: str | None = None
    compass_visible: bool = False


class RoomVastuAnalysis(BaseModel):
    """Vastu analysis for a specific room."""
    room: str
    direction: str
    status: VastuStatus
    analysis: str


class VastuDefect(BaseModel):
    """A Vastu defect identified in the floor plan."""
    issue: str
    severity: DefectSeverity
    impact: str


class VastuRemedy(BaseModel):
    """A remedy for a Vastu defect."""
    problem: str
    solution: str
    type: RemedyType


class AnalysisWarning(BaseModel):
    """A warning about the analysis quality or completeness."""
    type: AnalysisWarningType
    severity: AnalysisWarningSeverity
    message: str = Field(description="User-friendly warning message")
    suggestion: str = Field(description="Actionable suggestion to resolve the issue")


class VastuAnalysisResult(BaseModel):
    """Complete Vastu analysis result."""
    floor_plan_analysis: FloorPlanAnalysis
    vastu_score: int = Field(ge=1, le=10, description="Overall Vastu score from 1-10")
    score_explanation: str = Field(description="Explanation for the score")
    assumptions: list[str] = Field(default_factory=list, description="Assumptions made during analysis")
    room_analysis: list[RoomVastuAnalysis] = Field(default_factory=list)
    major_defects: list[VastuDefect] = Field(default_factory=list, description="Top 5 major defects")
    remedies: list[VastuRemedy] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list, description="Improvement suggestions")
    disclaimer: str = Field(description="Legal disclaimer")
    # New fields for edge case handling
    analysis_confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence level of the analysis (0.0-1.0)"
    )
    warnings: list[AnalysisWarning] = Field(
        default_factory=list,
        description="Warnings about analysis quality or missing data"
    )
    is_valid_floor_plan: bool = Field(
        default=True,
        description="Whether the image appears to be a valid floor plan"
    )


class VastuAnalyzeResponse(BaseModel):
    """API response for Vastu analysis."""
    success: bool
    data: VastuAnalysisResult | None = None
    report_markdown: str | None = None
    error: str | None = None
    # New fields for warning metadata
    has_warnings: bool = Field(default=False, description="Whether the analysis has warnings")
    warning_count: int = Field(default=0, description="Number of warnings")
    critical_warnings: bool = Field(default=False, description="Whether any warning is critical")
    provider_used: str
    analyzed_at: str = Field(default_factory=utc_now_iso)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "data": {
                    "floor_plan_analysis": {
                        "plot_shape": "rectangular",
                        "rooms": [
                            {"name": "Living Room", "direction": "North-East"}
                        ]
                    },
                    "vastu_score": 7,
                    "score_explanation": "Good overall layout with minor improvements needed",
                    "assumptions": ["North is at the top of the image"],
                    "room_analysis": [],
                    "major_defects": [],
                    "remedies": [],
                    "improvements": [],
                    "disclaimer": "This analysis is for informational purposes only."
                },
                "report_markdown": "# Vastu Analysis Report\n\n...",
                "provider_used": "gemini",
                "analyzed_at": "2025-12-30T10:00:00+00:00"
            }
        }
    )
