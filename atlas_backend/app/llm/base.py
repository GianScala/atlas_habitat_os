"""What a language model is, as far as the agent is concerned.

The agent asks one thing of a model: take the conversation so far and the
tools available, stream back what you are thinking and saying, and tell me
which tools you want run. Anthropic's cloud and a model running on this
machine under Ollama both answer that question; everything else about them
differs, and all of it is kept behind this interface.

THE COMMON SHAPE is Anthropic's content blocks — text, thinking, tool_use.
Not because the cloud is privileged, but because a thread on disk has to be
in some one format, that format was already this one, and it loses nothing:
it names every part of a turn that any of these models can produce. The
Ollama provider translates in both directions on the way past, so history
written by one model can be continued by another.
"""

from abc import ABC, abstractmethod
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

# Anything yielded mid-turn: one of the pydantic events in schemas.chat.
StreamEvent = Any

# The system prompt, either as plain text or as the list of content blocks
# `services/prompt.py` builds. Both are accepted everywhere: the blocks carry
# the cache breakpoint a hosted model needs, and a bare string is what a test
# — or anything that does not care — has always passed.
System = str | list[dict[str, Any]]


def system_text(system: System) -> str:
    """The system prompt flattened to the one string a local runtime wants."""
    if isinstance(system, str):
        return system
    return "".join(str(block.get("text", "")) for block in system)


@dataclass
class Turn:
    """One finished model turn.

    `content` is the assistant message exactly as it goes on disk and back to
    the model next round — tool_use blocks included, thinking signatures
    intact.
    """

    content: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        """The tool calls this turn asked for, in the order it asked."""
        return [block for block in self.content if block.get("type") == "tool_use"]


class Provider(ABC):
    """A model that can be asked a question and stream an answer back."""

    #: Stable key: "anthropic", "ollama".
    key: str = ""

    def __init__(self, model: str) -> None:
        self.model = model

    @property
    def label(self) -> str:
        """The model as a person would name it, e.g. "qwen3:8b (local)"."""
        return self.model

    @property
    def local(self) -> bool:
        """True when answering this question sends nothing off the machine."""
        return False

    @abstractmethod
    def stream(
        self,
        messages: list[dict[str, Any]],
        system: System,
        tools: list[dict[str, Any]],
    ) -> Generator[StreamEvent, None, Turn]:
        """Stream one turn.

        Yields display events as they happen and returns the finished Turn.
        Written as a generator so the caller can `yield from` it and receive
        the turn as the delegation's value.

        Raises ModelError for anything the person asking should be told about
        — a model that is not installed, a runtime that is not running, a key
        that was refused.
        """
        raise NotImplementedError

    def prewarm(self, system: System, tools: list[dict[str, Any]]) -> bool:
        """Pay for this prefix now, so no question has to pay for it later.

        A no-op by default, and that is the honest answer for a hosted model:
        the cloud does its own caching and there is nothing on this machine to
        prepare. Only a local runtime, which holds one KV cache and must
        prefill anything not already in it, has work to do here.
        """
        return True
