"""Request and response shapes for the chat API.

The event models double as the contract the frontend types mirror in
`atlas_frontend/src/lib/types.ts` — keep the two in step.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """One question, optionally continuing an existing thread."""

    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = Field(
        default=None,
        description="Omit to start a new conversation; the reply carries the new id.",
    )


class ToolCall(BaseModel):
    """A query the model decided to run."""

    id: str
    name: str
    input: dict[str, Any] = {}


class ToolResult(BaseModel):
    """What that query returned, summarised for display."""

    id: str
    name: str
    ok: bool
    has_data: bool
    queries: list[str] = []
    detail: str | None = None


# --- Server-sent events ---------------------------------------------------
#
# Every event on the stream is one of these, tagged by `type`.


class StartEvent(BaseModel):
    type: Literal["start"] = "start"
    conversation_id: str
    # Carried so a brand-new thread can appear in the sidebar immediately,
    # named, without a second request.
    title: str = ""

    # Which model is about to answer. Sent per turn rather than read from a
    # settings endpoint because it can be changed between two questions in the
    # same thread, and an answer should say which model produced it.
    provider: str = ""
    model: str = ""
    model_label: str = ""
    #: True when nothing about this answer leaves the machine.
    local: bool = False


class ThinkingDeltaEvent(BaseModel):
    type: Literal["thinking_delta"] = "thinking_delta"
    text: str


class TextDeltaEvent(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    text: str


class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    call: ToolCall


class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    result: ToolResult


class SourcesEvent(BaseModel):
    """The InfluxQL behind the answer, for the provenance footer."""

    type: Literal["sources"] = "sources"
    queries: list[str] = []


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    conversation_id: str
    stop_reason: str | None = None


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
    kind: str = "error"
    recoverable: bool = True
