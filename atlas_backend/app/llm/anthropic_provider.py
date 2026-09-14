"""The Anthropic cloud, behind the provider interface.

This is the code that used to live in the agent, moved out unchanged in
behaviour: same request, same streaming, same translation of SDK failures
into something worth reading. The one addition is that those failures now
leave as ModelError rather than being caught by the agent, so the agent
handles a cloud outage and a local runtime outage the same way.

WHAT THE CACHE BREAKPOINTS ARE FOR. This provider's equivalent of the local
one's prefill problem, and the same arithmetic. A request renders tools, then
system, then messages, and matches the cache by prefix — so a breakpoint on
the frozen half of the system prompt covers the tool schemas sitting in front
of it, and one on the end of the thread covers everything the earlier rounds
of this turn produced. Without them a five-round answer sends the same several
thousand tokens of rules and schemas five times and is billed for all five.
There are four breakpoints to spend per request; two are enough here.
"""

from collections.abc import Generator
from typing import Any

import anthropic

from app.config import Settings, get_settings
from app.core.errors import ConfigurationError, ModelError
from app.core.logging import get_logger
from app.llm.base import Provider, StreamEvent, System, Turn
from app.schemas.chat import TextDeltaEvent, ThinkingDeltaEvent

log = get_logger(__name__)

CACHE = {"type": "ephemeral"}


class AnthropicProvider(Provider):
    """Claude, over the Messages API."""

    key = "anthropic"

    def __init__(self, settings: Settings | None = None, model: str = "") -> None:
        self.settings = settings or get_settings()
        super().__init__(model or self.settings.anthropic_model)

        if not self.settings.anthropic_api_key:
            raise ConfigurationError(
                "ANTHROPIC_API_KEY is not set. Add it to the backend's .env "
                "file, or switch to a local model on the Models page."
            )

        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

    @property
    def label(self) -> str:
        return f"{self.model} (Anthropic)"

    def stream(
        self,
        messages: list[dict[str, Any]],
        system: System,
        tools: list[dict[str, Any]],
    ) -> Generator[StreamEvent, None, Turn]:
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.settings.anthropic_max_tokens,
            "system": _system(system),
            "tools": tools,
            "messages": _cached_tail(messages),
            "thinking": self.settings.thinking_param(),
            "output_config": {"effort": self.settings.anthropic_effort},
        }

        try:
            with self.client.messages.stream(**request) as stream:
                for event in stream:
                    emitted = _delta_event(event)
                    if emitted is not None:
                        yield emitted
                final = stream.get_final_message()
                _log_cache(final)
        except anthropic.AuthenticationError as exc:
            raise ModelError(
                "Anthropic rejected the API key. Check ANTHROPIC_API_KEY.",
                kind="auth",
                recoverable=False,
            ) from exc
        except anthropic.RateLimitError as exc:
            raise ModelError(
                "Rate limited by the Anthropic API — wait a moment and retry.",
                kind="rate_limit",
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ModelError(
                "Could not reach the Anthropic API. Check the connection.",
                kind="network",
            ) from exc
        except anthropic.APIStatusError as exc:
            raise ModelError(
                f"Anthropic API error {exc.status_code}: {exc.message}", kind="model"
            ) from exc

        return Turn(content=_serialise(final.content), stop_reason=final.stop_reason)


def _system(system: System) -> list[dict[str, Any]]:
    """The system prompt as content blocks, breakpoint intact.

    `services/prompt.py` already returns blocks with the breakpoint on the
    frozen half. A bare string arrives from anything that did not care — and
    gets a breakpoint of its own here, since a caller who hands us one string
    is telling us the whole thing is fixed.
    """
    if isinstance(system, str):
        return [{"type": "text", "text": system, "cache_control": CACHE}] if system else []
    return list(system)


def _cached_tail(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The thread with a cache breakpoint on its last block.

    One turn here is several rounds, and every round re-sends everything the
    rounds before it produced: the assistant's tool_use blocks, then the JSON
    the queries returned, which is the bulk of it. Marked, round N's request
    reads round N-1's prefix instead of paying for it again, and the same
    entry serves the next question in the thread.

    Anthropic looks back at most twenty content blocks from a breakpoint to
    find an earlier one, so this only holds while a round adds fewer than that
    — one assistant turn plus its results, which is comfortably inside it
    unless a model asks for a dozen queries at once. That case loses the read
    and pays full price; it does not fail.

    The copy is not incidental. `messages` is the conversation's own list of
    its own stored dicts, and annotating them in place would write a cache
    breakpoint into the thread on disk — which would then be sent back, in the
    wrong place, on every later round.
    """
    if not messages:
        return messages

    head, last = messages[:-1], dict(messages[-1])
    content = last.get("content")

    if isinstance(content, str):
        # A question someone typed. It becomes a one-block list to carry the
        # breakpoint; the API reads the two forms identically.
        last["content"] = [{"type": "text", "text": content, "cache_control": CACHE}]
    elif isinstance(content, list) and content:
        blocks = [dict(block) for block in content]
        blocks[-1]["cache_control"] = CACHE
        last["content"] = blocks
    else:
        return messages

    return head + [last]


def _log_cache(final: Any) -> None:
    """Report what the cache did, because a silent miss looks like nothing.

    A breakpoint that stops matching costs latency and money and changes no
    behaviour at all, so it would go unnoticed indefinitely. `read` at zero on
    a round that is not the first means something in the prefix moved.
    """
    usage = getattr(final, "usage", None)
    if usage is None:
        return
    log.info(
        "tokens: %s in, %s cache read, %s cache write, %s out",
        getattr(usage, "input_tokens", "?"),
        getattr(usage, "cache_read_input_tokens", "?"),
        getattr(usage, "cache_creation_input_tokens", "?"),
        getattr(usage, "output_tokens", "?"),
    )


def _delta_event(event: Any) -> StreamEvent | None:
    """Translate one SDK stream event into ours, or None if it is not ours."""
    if event.type != "content_block_delta":
        return None

    delta = event.delta
    if delta.type == "text_delta":
        return TextDeltaEvent(text=delta.text)
    if delta.type == "thinking_delta":
        return ThinkingDeltaEvent(text=delta.thinking)
    return None  # signature and partial-JSON deltas are internal


def _serialise(content: list[Any]) -> list[dict[str, Any]]:
    """Content blocks as plain dicts, so history stays JSON-serialisable.

    Thinking blocks keep their signature — the API rejects modified ones — and
    unset optional fields are dropped rather than sent back as nulls.
    """
    return [block.model_dump(mode="json", exclude_none=True) for block in content]
