"""The agent loop: question in, streamed answer out.

One turn is a cycle. The model reads the question, decides which queries to
run, the queries run against the habitat database through the tool registry,
and the model answers from what came back. It may go round several times; the
loop stops when the model returns text with no further tool calls.

Everything is yielded as it happens - thinking, text tokens, each query and
its outcome - so the interface can show the work rather than a spinner.

The loop does not know which model it is driving. A provider (see `app/llm/`)
takes the thread and the tools and streams a turn back, whether the weights
are on this machine or in Anthropic's data centre; the shape of the work is
the same either way, and so is this file.

This module is a synchronous generator on purpose. Both providers and every
data-source adapter are blocking, and Starlette runs a sync stream in its
threadpool, so this stays simple and correct without an async rewrite.
"""

from collections.abc import Iterator
from typing import Any

from app.config import Settings, get_settings
from app.core.errors import AtlasError, DatasourceError, ModelError
from app.core.logging import get_logger
from app.llm import warm
from app.llm.base import Provider, Turn
from app.schemas.chat import (
    DoneEvent,
    ErrorEvent,
    SourcesEvent,
    StartEvent,
    ToolCall,
    ToolCallEvent,
    ToolResult,
    ToolResultEvent,
)
from app.services.prompt import system_prompt
from app.storage.conversation_repository import Conversation, unanswered_result
from app.tools import registry

log = get_logger(__name__)

AgentEvent = Any  # one of the pydantic event models in schemas.chat


class Agent:
    """Runs one question to completion against a conversation's history."""

    def __init__(self, provider: Provider, settings: Settings | None = None):
        self.provider = provider
        self.settings = settings or get_settings()
        # Set at the top of `run`, and held for that run only.
        self._system: list[dict[str, Any]] = []

    # -- public ------------------------------------------------------------

    def run(self, conversation: Conversation, question: str) -> Iterator[AgentEvent]:
        """Answer `question`, yielding events as the work happens.

        The conversation is mutated in place, so the thread carries forward.
        """
        conversation.append({"role": "user", "content": question})

        # Built once for the whole turn rather than once per round. The plan
        # and the style are read from SQLite, and a crew editing a ceiling
        # halfway through a five-round answer should not have the model change
        # its instructions underneath itself mid-thought.
        self._system = system_prompt(self.provider)

        yield StartEvent(
            conversation_id=conversation.id,
            title=conversation.title,
            provider=self.provider.key,
            model=self.provider.model,
            model_label=self.provider.label,
            local=self.provider.local,
        )

        queries_used: list[str] = []

        # Held for the whole answer, not per round: a local runtime serves one
        # request at a time, so any housekeeping it might otherwise do would be
        # queued in front of this question — including in the gaps between
        # rounds, where a fresh one could otherwise slip in and stall round
        # three. Someone is waiting; nothing else gets the model until they
        # have their answer.
        with warm.priority():
            try:
                yield from self._rounds(conversation, queries_used)
            except ModelError as exc:
                yield ErrorEvent(
                    message=exc.message, kind=exc.kind, recoverable=exc.recoverable
                )
            except DatasourceError as exc:
                yield ErrorEvent(
                    message=f"Habitat data unreachable: {exc.message}", kind="datasource"
                )
            except AtlasError as exc:
                yield ErrorEvent(message=exc.message, kind="backend")
            else:
                if queries_used:
                    yield SourcesEvent(queries=queries_used)

        yield DoneEvent(conversation_id=conversation.id)

    # -- the loop ----------------------------------------------------------

    def _rounds(
        self, conversation: Conversation, queries_used: list[str]
    ) -> Iterator[AgentEvent]:
        """Up to max_tool_rounds cycles of query-then-answer."""
        for round_number in range(self.settings.max_tool_rounds):
            turn = yield from self.provider.stream(
                messages=conversation.api_messages(
                    self.settings.max_turns_per_conversation
                ),
                system=self._system,
                tools=registry.schemas(),
            )

            if turn.stop_reason == "refusal":
                yield ErrorEvent(
                    message="I can't answer that one.", kind="refusal", recoverable=True
                )
                return

            if not _said_anything(turn):
                # Nothing to show and nothing to run: a model that thought and
                # then stopped, or returned an empty message. Storing it would
                # leave an assistant turn in the thread that says nothing,
                # which some models then refuse to continue from — and would
                # leave the reader watching a spinner end in silence.
                yield ErrorEvent(
                    message=(
                        f"{self.provider.model} returned an empty answer. Try "
                        "asking again, or pick a different model."
                    ),
                    kind="empty_answer",
                )
                return

            # The full content list must go back, tool_use blocks included.
            conversation.append({"role": "assistant", "content": turn.content})

            tool_uses = turn.tool_uses
            if not tool_uses:
                if turn.stop_reason == "max_tokens":
                    yield ErrorEvent(
                        message=(
                            "The answer was cut off at the model's length "
                            "limit. Ask for a narrower slice of it."
                        ),
                        kind="max_tokens",
                    )
                log.info("Answered in %d round(s)", round_number + 1)
                return

            yield from self._run_tools(conversation, tool_uses, queries_used)

        yield ErrorEvent(
            message=(
                "I ran out of query attempts on that one — try narrowing the "
                "question to one measurement or a shorter time window."
            ),
            kind="tool_rounds_exhausted",
        )

    def _run_tools(
        self,
        conversation: Conversation,
        tool_uses: list[dict[str, Any]],
        queries_used: list[str],
    ) -> Iterator[AgentEvent]:
        """Run every requested tool, then send all results back in ONE message.

        Splitting results across several user messages teaches the model to
        stop calling tools in parallel, so they are batched here.

        The assistant message carrying the `tool_use` blocks is already on
        disk by the time we get here, and the API rejects any history where
        one of those goes unanswered. So the batch is seeded with a failure
        per call and written in a `finally`: a tool that raises, or a client
        that hangs up mid-answer, still leaves a matched pair behind.
        """
        results = [unanswered_result(str(block.get("id", ""))) for block in tool_uses]

        try:
            for index, block in enumerate(tool_uses):
                call_id = str(block.get("id", ""))
                name = str(block.get("name", ""))
                arguments = dict(block.get("input") or {})

                yield ToolCallEvent(
                    call=ToolCall(id=call_id, name=name, input=arguments)
                )

                log.info("Running tool %s", name)
                outcome = registry.run_tool(name, arguments)

                for query in outcome.queries:
                    if query not in queries_used:
                        queries_used.append(query)

                yield ToolResultEvent(
                    result=ToolResult(
                        id=call_id,
                        name=name,
                        ok=not outcome.is_error,
                        has_data=bool(outcome.raw.get("data")),
                        queries=outcome.queries,
                        detail=outcome.content if outcome.is_error else None,
                    )
                )

                results[index] = {
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": outcome.content,
                    "is_error": outcome.is_error,
                }
        finally:
            conversation.append({"role": "user", "content": results})


def _said_anything(turn: Turn) -> bool:
    """Did this turn produce an answer, or ask for a query?

    Reasoning alone does not count. It is worth storing and worth showing, but
    a turn that only thought has not answered the question.
    """
    if turn.tool_uses:
        return True
    return any(
        block.get("type") == "text" and str(block.get("text", "")).strip()
        for block in turn.content
    )
