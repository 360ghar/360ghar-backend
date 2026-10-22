"""Pydantic schemas for the AI agent chat feature.

Covers the write bodies, the conversation list items and every typed SSE frame
the agent stream emits. ``AgentStreamFrame`` is the single union of frames; the
agent service builds frames through it and the OpenAPI document publishes it.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, TypeAdapter, model_validator

from app.mcp.chatgpt.widget_payloads import (
    LeaseDetailsPayload,
    LeaseManagementPayload,
    MaintenancePayload,
    OwnerDashboardPayload,
    PropertyDetailsPayload,
    PropertySearchPayload,
    PropertySwipePayload,
    RentCollectionPayload,
    TenantRentPayload,
    VisitListPayload,
    VisitSchedulerPayload,
)
from app.schemas.base import UtcDateTime, WriteModel

# Fixed text for every error frame. The exception detail is logged, never sent.
AGENT_ERROR_MESSAGE = "The assistant could not finish this reply. Try again."

# Error codes an error frame can carry. Every code is emitted by the server today.
AgentErrorCode = Literal["AGENT_ERROR", "STREAM_ERROR"]


CONTEXT_MESSAGE_MAX = 500


class ChatContext(WriteModel):
    """The page the visitor asks about. A closed set: the server loads the facts itself.

    A property is named by ``id``, a locality by ``slug``. Nothing else is accepted, so a client
    cannot put its own text into the model's context through this field.
    """

    type: Literal["property", "locality"]
    id: int | None = Field(default=None, ge=1, le=10**15, description="Property id (type property)")
    slug: str | None = Field(
        default=None, min_length=1, max_length=200, pattern=r"^[a-z0-9][a-z0-9-]*$",
        description="Locality slug (type locality)",
    )

    @model_validator(mode="after")
    def _one_key_for_type(self) -> ChatContext:
        if self.type == "property" and (self.id is None or self.slug is not None):
            raise ValueError("a property context needs id and no slug")
        if self.type == "locality" and (self.slug is None or self.id is not None):
            raise ValueError("a locality context needs slug and no id")
        return self


def _check_context_message(message: str, context: ChatContext | None) -> None:
    if context is not None and len(message) > CONTEXT_MESSAGE_MAX:
        raise ValueError(f"message must be at most {CONTEXT_MESSAGE_MAX} characters when context is set")


class AgentChatRequest(WriteModel):
    """Request body for POST /agent/chat."""

    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: int | None = Field(
        default=None, description="Existing conversation to continue. Omit to start one."
    )
    context: ChatContext | None = Field(
        default=None,
        description="Optional page to ground the answer in. With it the message is at most 500 characters.",
    )

    @model_validator(mode="after")
    def _context_cap(self) -> AgentChatRequest:
        _check_context_message(self.message, self.context)
        return self


class GuestChatRequest(WriteModel):
    """Request body for POST /agent/chat-public (no auth)."""

    message: str = Field(..., min_length=1, max_length=4000)
    context: ChatContext | None = Field(
        default=None,
        description=(
            "Optional page to ground the answer in. With it the message is at most 500 characters "
            "and the call is limited to 10 per minute and 40 per day per IP."
        ),
    )

    @model_validator(mode="after")
    def _context_cap(self) -> GuestChatRequest:
        _check_context_message(self.message, self.context)
        return self


class AIConversationSummary(BaseModel):
    """An agent conversation in the list. Named apart from the flatmates ConversationSummary."""

    id: int
    title: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime
    message_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class ConversationMessageOut(BaseModel):
    """A stored message. Widget rows carry widget_name and widget_data."""

    id: int
    role: str = Field(description="user, assistant or widget.")
    content: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    widget_name: str | None = None
    widget_data: dict[str, Any] | None = None
    created_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _populate_widget_fields(self) -> ConversationMessageOut:
        """Map DB columns to widget fields for widget messages."""
        if self.role == "widget":
            self.widget_name = self.tool_name
            self.widget_data = self.tool_result
        return self


# ---------------------------------------------------------------------------
# SSE frames. Each frame is {"event": <name>, "data": <payload>}. The frame
# name is the SSE event name; the payload is the SSE data line.
# ---------------------------------------------------------------------------


class ConversationInfoData(BaseModel):
    conversation_id: int


class TextChunkData(BaseModel):
    text: str


class ToolCallStartData(BaseModel):
    call_id: str
    tool: str


class ToolCallEndData(BaseModel):
    call_id: str
    tool: str
    success: bool


class PropertySearchWidgetData(BaseModel):
    widget_name: Literal["PropertySearchWidget"]
    structured_content: PropertySearchPayload | None = None


class PropertyDetailsWidgetData(BaseModel):
    widget_name: Literal["PropertyDetailsWidget"]
    structured_content: PropertyDetailsPayload | None = None


class PropertySwipeWidgetData(BaseModel):
    widget_name: Literal["PropertySwipeWidget"]
    structured_content: PropertySwipePayload | None = None


class VisitSchedulerWidgetData(BaseModel):
    widget_name: Literal["VisitSchedulerWidget"]
    structured_content: VisitSchedulerPayload | None = None


class VisitListWidgetData(BaseModel):
    widget_name: Literal["VisitListWidget"]
    structured_content: VisitListPayload | None = None


class LeaseDetailsWidgetData(BaseModel):
    widget_name: Literal["LeaseDetailsWidget"]
    structured_content: LeaseDetailsPayload | None = None


class MaintenanceWidgetData(BaseModel):
    widget_name: Literal["MaintenanceWidget"]
    structured_content: MaintenancePayload | None = None


class OwnerDashboardWidgetData(BaseModel):
    widget_name: Literal["OwnerDashboardWidget"]
    structured_content: OwnerDashboardPayload | None = None


class LeaseManagementWidgetData(BaseModel):
    widget_name: Literal["LeaseManagementWidget"]
    structured_content: LeaseManagementPayload | None = None


class RentCollectionWidgetData(BaseModel):
    widget_name: Literal["RentCollectionWidget"]
    structured_content: RentCollectionPayload | None = None


class TenantRentWidgetData(BaseModel):
    widget_name: Literal["TenantRentWidget"]
    structured_content: TenantRentPayload | None = None


# One frame-data model per widget name, keyed by widget_name. OpenAPI publishes this
# union; each structured_content is the payload model the producer validates into.
WidgetData = Annotated[
    PropertySearchWidgetData
    | PropertyDetailsWidgetData
    | PropertySwipeWidgetData
    | VisitSchedulerWidgetData
    | VisitListWidgetData
    | LeaseDetailsWidgetData
    | MaintenanceWidgetData
    | OwnerDashboardWidgetData
    | LeaseManagementWidgetData
    | RentCollectionWidgetData
    | TenantRentWidgetData,
    Field(discriminator="widget_name"),
]

_WIDGET_DATA_ADAPTER: TypeAdapter[WidgetData] = TypeAdapter(WidgetData)


def make_widget_data(widget_name: str, structured_content: dict[str, Any]) -> WidgetData:
    """Typed frame data for one widget result. Raises ValidationError for an unknown name."""
    return _WIDGET_DATA_ADAPTER.validate_python(
        {"widget_name": widget_name, "structured_content": structured_content}
    )


def widget_result_dict(widget: WidgetData) -> dict[str, Any] | None:
    """The JSON object stored as a widget row's tool_result."""
    if widget.structured_content is None:
        return None
    return widget.structured_content.model_dump(mode="json", exclude_unset=True)


class DoneData(BaseModel):
    response_text: str


class ErrorData(BaseModel):
    code: AgentErrorCode
    message: str = Field(description="Fixed text. Details are logged on the server.")


class ConversationInfoFrame(BaseModel):
    event: Literal["conversation_info"] = "conversation_info"
    data: ConversationInfoData


class TextChunkFrame(BaseModel):
    event: Literal["text_chunk"] = "text_chunk"
    data: TextChunkData


class ToolCallStartFrame(BaseModel):
    event: Literal["tool_call_start"] = "tool_call_start"
    data: ToolCallStartData


class ToolCallEndFrame(BaseModel):
    event: Literal["tool_call_end"] = "tool_call_end"
    data: ToolCallEndData


class WidgetFrame(BaseModel):
    event: Literal["widget"] = "widget"
    data: WidgetData


class DoneFrame(BaseModel):
    event: Literal["done"] = "done"
    data: DoneData


class ErrorFrame(BaseModel):
    event: Literal["error"] = "error"
    data: ErrorData


AgentStreamFrame = Annotated[
    ConversationInfoFrame
    | TextChunkFrame
    | ToolCallStartFrame
    | ToolCallEndFrame
    | WidgetFrame
    | DoneFrame
    | ErrorFrame,
    Field(discriminator="event"),
]


class AgentStreamEvent(RootModel[AgentStreamFrame]):
    """One typed SSE frame of POST /agent/chat. Lets OpenAPI publish the frame union.

    The stream writes frames with ``sse_frame``; this model is for the schema only.
    """


__all__ = [
    "AGENT_ERROR_MESSAGE",
    "AIConversationSummary",
    "AgentChatRequest",
    "AgentErrorCode",
    "AgentStreamEvent",
    "AgentStreamFrame",
    "ConversationInfoData",
    "ConversationInfoFrame",
    "ConversationMessageOut",
    "DoneData",
    "DoneFrame",
    "ErrorData",
    "ErrorFrame",
    "GuestChatRequest",
    "TextChunkData",
    "TextChunkFrame",
    "ToolCallEndData",
    "ToolCallEndFrame",
    "ToolCallStartData",
    "ToolCallStartFrame",
    "WidgetData",
    "WidgetFrame",
    "make_widget_data",
    "widget_result_dict",
]
