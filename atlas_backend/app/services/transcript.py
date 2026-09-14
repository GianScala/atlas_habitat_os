"""Turning stored API messages back into a readable transcript.

The history we keep is exactly what the Messages API needs: user strings,
assistant content blocks, and `tool_result` blocks wrapped in user messages.
That is the right thing to store — one source of truth, replayable to the
model verbatim — but it is not what a person reads.

This module projects it into the same shape the live event stream produces,
so reopening a thread looks identical to having watched it arrive. Nothing is
stored twice, and the two views cannot drift apart.
"""

import json
from typing import Any

from app.schemas.conversations import TranscriptMessage, TranscriptTraceStep

# One API round trip can produce several assistant messages — text, then a
# tool call, then more text. They are one bubble to the reader.


def to_transcript(messages: list[dict[str, Any]]) -> list[TranscriptMessage]:
    """Project stored messages into renderable turns."""
    transcript: list[TranscriptMessage] = []
    assistant: TranscriptMessage | None = None
    steps_by_id: dict[str, TranscriptTraceStep] = {}

    def flush() -> None:
        nonlocal assistant
        if assistant is not None:
            assistant.sources = _collect_sources(assistant.trace)
            transcript.append(assistant)
            assistant = None

    for index, message in enumerate(messages):
        role = message.get("role")
        content = message.get("content")

        if role == "user" and isinstance(content, str):
            flush()
            transcript.append(
                TranscriptMessage(id=f"m{index}", role="user", content=content)
            )
            continue

        if role == "user" and isinstance(content, list):
            _apply_tool_results(content, steps_by_id)
            continue

        if role == "assistant" and isinstance(content, list):
            if assistant is None:
                assistant = TranscriptMessage(id=f"m{index}", role="assistant")
            _apply_assistant_blocks(content, assistant, steps_by_id)
            continue

        if role == "assistant" and isinstance(content, str):
            # Older or hand-written history; still worth showing.
            if assistant is None:
                assistant = TranscriptMessage(id=f"m{index}", role="assistant")
            assistant.content += content

    flush()
    return transcript


def _apply_assistant_blocks(
    blocks: list[Any],
    assistant: TranscriptMessage,
    steps_by_id: dict[str, TranscriptTraceStep],
) -> None:
    """Fold one assistant message's content blocks into the current bubble."""
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")

        if kind == "text":
            assistant.content += block.get("text", "")

        elif kind == "thinking":
            assistant.thinking += block.get("thinking", "")

        elif kind == "tool_use":
            # Text written before a query and text written after it are
            # separate thoughts. Without a break they read as a run-on.
            if assistant.content and not assistant.content.endswith("\n\n"):
                assistant.content = assistant.content.rstrip() + "\n\n"

            step = TranscriptTraceStep(
                id=str(block.get("id", "")),
                name=str(block.get("name", "")),
                input=dict(block.get("input") or {}),
                status="running",
            )
            assistant.trace.append(step)
            steps_by_id[step.id] = step


def _apply_tool_results(
    blocks: list[Any], steps_by_id: dict[str, TranscriptTraceStep]
) -> None:
    """Resolve the trace steps a batch of tool results belongs to."""
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue

        step = steps_by_id.get(str(block.get("tool_use_id", "")))
        if step is None:
            continue

        raw = block.get("content")
        text = raw if isinstance(raw, str) else json.dumps(raw, default=str)

        if block.get("is_error"):
            step.status = "failed"
            step.detail = text
            continue

        payload = _parse(text)
        step.queries = _queries_of(payload)
        step.status = "ok" if payload.get("data") else "empty"


def _parse(text: str) -> dict[str, Any]:
    """A tool result's JSON, or an empty dict if it was not JSON."""
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _queries_of(payload: dict[str, Any]) -> list[str]:
    """The queries a tool result reports having run, in the adapter's dialect."""
    found = payload.get("queries") or [payload.get("query")]
    return [q for q in found if isinstance(q, str) and q]


def _collect_sources(trace: list[TranscriptTraceStep]) -> list[str]:
    """The distinct queries behind one answer, in the order they ran."""
    sources: list[str] = []
    for step in trace:
        for query in step.queries:
            if query not in sources:
                sources.append(query)
    return sources
