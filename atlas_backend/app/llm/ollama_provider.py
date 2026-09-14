"""A model running on this machine, behind the provider interface.

Same contract as the Anthropic provider, and the same agent loop drives both.
The differences are all in here:

  NOTHING LEAVES THE MACHINE. The question, the telemetry it pulls back, and
  the answer stay on localhost. That is the point of this provider.

  REASONING ARRIVES TWO WAYS. Ollama puts it in a `thinking` field for models
  that declare the capability; others simply write <think>…</think> into the
  content and expect the reader to sort it out. Both are routed to the same
  thinking events, so the interface never has to know which kind it is talking
  to. See `ThinkStream`.

  ASKING FOR THINKING IS AN ERROR ON A MODEL THAT CANNOT. Rather than keep a
  list of which can, the first request asks and a refusal is retried without
  it — the daemon knows better than we do, and it tells us for free.
"""

from collections.abc import Generator, Iterator
from itertools import chain
from typing import Any

from app.config import Settings, get_settings
from app.core.errors import ModelError
from app.core.logging import get_logger
from app.llm import catalogue, translate
from app.llm.base import Provider, StreamEvent, System, Turn
from app.llm.ollama_client import OllamaClient
from app.schemas.chat import TextDeltaEvent, ThinkingDeltaEvent

log = get_logger(__name__)

OPEN_TAG = "<think>"
CLOSE_TAG = "</think>"


class OllamaProvider(Provider):
    """One local model, served by the Ollama daemon."""

    key = "ollama"

    def __init__(self, settings: Settings | None = None, model: str = "") -> None:
        self.settings = settings or get_settings()
        super().__init__(catalogue.canonical(model or self.settings.ollama_model))
        self.client = OllamaClient(self.settings.ollama_base, self.settings.ollama_timeout)

    @property
    def label(self) -> str:
        return f"{self.model} (local)"

    @property
    def local(self) -> bool:
        return True

    # -- one turn ----------------------------------------------------------

    def stream(
        self,
        messages: list[dict[str, Any]],
        system: System,
        tools: list[dict[str, Any]],
    ) -> Generator[StreamEvent, None, Turn]:
        payload = self._payload(messages, system, tools, stream=True)
        chunks = self._open(payload)

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_uses: list[dict[str, Any]] = []
        tags = ThinkStream()
        done_reason: str | None = None

        for chunk in chunks:
            message = chunk.get("message") or {}

            reasoning = message.get("thinking")
            if reasoning:
                thinking_parts.append(str(reasoning))
                yield ThinkingDeltaEvent(text=str(reasoning))

            content = message.get("content")
            if content:
                for channel, piece in tags.feed(str(content)):
                    if channel == "thinking":
                        thinking_parts.append(piece)
                        yield ThinkingDeltaEvent(text=piece)
                    else:
                        text_parts.append(piece)
                        yield TextDeltaEvent(text=piece)

            for call in message.get("tool_calls") or []:
                function = (call or {}).get("function") or {}
                name = str(function.get("name", ""))
                if not name:
                    continue
                tool_uses.append(
                    translate.tool_use_block(name, function.get("arguments"))
                )

            if chunk.get("done"):
                done_reason = chunk.get("done_reason")

        for channel, piece in tags.flush():
            if channel == "thinking":
                thinking_parts.append(piece)
                yield ThinkingDeltaEvent(text=piece)
            else:
                text_parts.append(piece)
                yield TextDeltaEvent(text=piece)

        return _turn(text_parts, thinking_parts, tool_uses, done_reason)

    # -- warming the cache -------------------------------------------------

    def prewarm(self, system: System, tools: list[dict[str, Any]]) -> bool:
        """Prefill the fixed prefix into Ollama's KV cache, and stop there.

        The system prompt and the tool schemas are the same several thousand
        tokens on every round of every turn, and this machine prefills at a
        rate that makes them worth about a minute of silence whenever the
        cache does not already hold them. Cached, the same tokens cost
        fractions of a second.

        So the cost is real but its TIMING is negotiable, and that is the whole
        trick: send the prefix once when nobody is waiting — at boot, and after
        a model switch — and the person who asks the first question finds it
        already there. One token of output is asked for, because the point is
        reached the moment the prefill is done and generating more of an answer
        nobody will read only holds the runner longer.

        The trailing message is deliberately trivial. Ollama reuses whatever
        prefix a later request shares, so only the part before it — the system
        prompt and the tools — needs to match what a real turn sends. That it
        does match is not luck: the payload comes from the same builder.

        Once started this runs to the end; see `OllamaClient.chat_once` for why
        it cannot usefully be interrupted, and why that matters less than it
        sounds. What keeps it out of a waiting person's way is not stopping it
        but not starting it — `warm.priority()`.
        """
        payload = self._payload(
            [{"role": "user", "content": "ready"}], system, tools, stream=False
        )
        payload["options"]["num_predict"] = 1

        try:
            self.client.chat_once(payload)
            return True
        except ModelError as exc:
            # Same refusal `_open` handles, and it has to be handled the same
            # way here: a warm-up that gave up on a model with no thinking
            # would leave that model paying the full prefill on its first
            # question, which is the one case this exists to prevent.
            if "think" in payload and _refused_thinking(exc):
                payload.pop("think")
                self.client.chat_once(payload)
                return True
            raise

    # -- the request -------------------------------------------------------

    def _payload(
        self,
        messages: list[dict[str, Any]],
        system: System,
        tools: list[dict[str, Any]],
        stream: bool,
    ) -> dict[str, Any]:
        """The request body, built in one place for every caller.

        `prewarm` is only worth anything if the prefix it sends is byte-for-byte
        the one a real turn sends, and `options` matters as much as the text:
        Ollama starts a fresh runner — dropping the cache the warm-up just
        filled — when num_ctx or the rest of them differ. Hence one builder
        rather than two payloads that look the same today.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": translate.to_ollama_messages(system, messages),
            "tools": translate.to_ollama_tools(tools),
            "stream": stream,
            "keep_alive": self.settings.ollama_keep_alive,
            "options": {
                "num_ctx": self.settings.ollama_num_ctx,
                "num_predict": self.settings.ollama_max_tokens,
                "temperature": self.settings.ollama_temperature,
            },
        }
        # Sent either way, never omitted. Qwen3 and the other thinking models
        # reason BY DEFAULT under Ollama, so leaving the field out does not
        # turn reasoning off — it leaves it on and costs a few hundred tokens
        # of it before every answer. Saying `false` is the only way to mean no.
        # A model with no thinking to speak of rejects the field entirely;
        # `_open` drops it and asks again.
        #
        # It also changes the rendered prompt, so a warm-up that disagreed with
        # the turn it is warming for would cache the wrong tokens.
        payload["think"] = self._thinking_wanted()
        return payload

    def _thinking_wanted(self) -> bool:
        return self.settings.ollama_thinking.lower() != "disabled"

    def _open(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Start the stream, having asked the daemon what it will accept.

        `chat` builds a generator and sends nothing until it is advanced, so
        pulling the first chunk here is what surfaces a refusal — early
        enough that the request can be adjusted and repeated without any of
        it having reached the reader.
        """
        try:
            return self._first(payload)
        except ModelError as exc:
            if "think" in payload and _refused_thinking(exc):
                log.info("%s does not support thinking; retrying without it", self.model)
                payload.pop("think")
                return self._first(payload)
            raise self._clearer(exc) from exc

    def _first(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        stream = self.client.chat(payload)
        opening = next(stream, None)
        return stream if opening is None else chain([opening], stream)

    def _clearer(self, exc: ModelError) -> ModelError:
        """Name the model and the way out when the daemon says it has no such thing."""
        if exc.kind != "model_not_installed":
            return exc
        return ModelError(
            f"The model {self.model} is not installed. Open the Models page "
            "and install it, or pick one that is.",
            kind="model_not_installed",
            recoverable=False,
        )


def _turn(
    text_parts: list[str],
    thinking_parts: list[str],
    tool_uses: list[dict[str, Any]],
    done_reason: str | None,
) -> Turn:
    """Assemble the finished turn in the shape the rest of the app stores.

    The reasoning is kept in the stored turn even though it is never sent back
    to the model (see `translate`). Storing it is what makes a reopened thread
    look like the one that was watched arriving; dropping it would leave the
    reader with an answer and no account of how it was reached.
    """
    content: list[dict[str, Any]] = []

    thinking = "".join(thinking_parts).strip()
    if thinking:
        content.append({"type": "thinking", "thinking": thinking})

    text = "".join(text_parts).strip()
    if text:
        content.append({"type": "text", "text": text})
    content.extend(tool_uses)

    if tool_uses:
        stop_reason = "tool_use"
    elif done_reason == "length":
        stop_reason = "max_tokens"
    else:
        stop_reason = "end_turn"

    return Turn(content=content, stop_reason=stop_reason)


def _refused_thinking(exc: ModelError) -> bool:
    """Is this the daemon saying the model has no thinking to show?"""
    reason = exc.message.lower()
    return "think" in reason and ("support" in reason or "capab" in reason)


class ThinkStream:
    """Splits streamed text into reasoning and answer on <think> tags.

    Tags do not respect chunk boundaries — `<thi` can arrive at the end of one
    chunk and `nk>` at the start of the next — so anything that could still
    become a tag is held back until the next chunk proves it either way, and
    released by `flush` when the turn ends.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    @property
    def _channel(self) -> str:
        return "thinking" if self._inside else "text"

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        """(channel, piece) pairs ready to show, in order."""
        self._buffer += chunk
        ready: list[tuple[str, str]] = []

        while True:
            tag = CLOSE_TAG if self._inside else OPEN_TAG
            at = self._buffer.find(tag)
            if at == -1:
                break
            if at > 0:
                ready.append((self._channel, self._buffer[:at]))
            self._buffer = self._buffer[at + len(tag) :]
            self._inside = not self._inside

        held = _partial_tag(self._buffer, CLOSE_TAG if self._inside else OPEN_TAG)
        release = self._buffer[: len(self._buffer) - held]
        self._buffer = self._buffer[len(self._buffer) - held :]
        if release:
            ready.append((self._channel, release))

        return ready

    def flush(self) -> list[tuple[str, str]]:
        """Whatever is still held back at the end of the turn."""
        if not self._buffer:
            return []
        remainder = [(self._channel, self._buffer)]
        self._buffer = ""
        return remainder


def _partial_tag(text: str, tag: str) -> int:
    """How many trailing characters could still turn out to be `tag`."""
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if tag.startswith(text[-size:]):
            return size
    return 0
