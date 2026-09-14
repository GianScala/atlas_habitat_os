"""Shapes for stored chat threads.

`TranscriptMessage` is what the interface renders when an old thread is
reopened. It mirrors the shape the live event stream builds up, so a reloaded
conversation looks identical to one you just watched arrive.
"""

from typing import Any, Literal

from pydantic import BaseModel

TraceStatus = Literal["running", "ok", "empty", "failed"]


class TranscriptTraceStep(BaseModel):
    """One query, as it is shown in the trace panel."""

    id: str
    name: str
    input: dict[str, Any] = {}
    status: TraceStatus = "ok"
    queries: list[str] = []
    detail: str | None = None


class TranscriptMessage(BaseModel):
    """One turn, ready to render."""

    id: str
    role: Literal["user", "assistant"]
    content: str = ""
    thinking: str = ""
    trace: list[TranscriptTraceStep] = []
    sources: list[str] = []


class ConversationSummary(BaseModel):
    """A row in the sidebar."""

    conversation_id: str
    title: str
    created_at: float
    updated_at: float
    message_count: int


class ConversationDetail(ConversationSummary):
    """A thread with its full transcript."""

    messages: list[TranscriptMessage] = []


class DeleteResult(BaseModel):
    deleted: int
