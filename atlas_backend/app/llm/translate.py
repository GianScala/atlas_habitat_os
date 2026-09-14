"""Between our history and Ollama's chat format.

Our threads are stored as Anthropic content blocks (see `llm/base.py` for
why). Ollama's /api/chat wants something flatter: a list of messages where an
assistant turn carries `tool_calls` alongside its text, and each tool result
is its own message on a `tool` role.

The conversions are not quite symmetrical, and the asymmetries are the whole
content of this module:

  IDS. Anthropic gives every tool call an id and matches results to it. Ollama
  matches by position and name. We mint ids on the way in — the pairing logic
  in `conversation_repository` depends on them — and resolve them back to
  names on the way out, which is why translating a thread has to walk it in
  order rather than message by message.

  THINKING. A model's reasoning is not sent back to it next round. Anthropic
  requires the signed block back verbatim; Ollama's models are trained the
  other way, on threads where only the conclusion survives. So thinking blocks
  are dropped here, and only here.
"""

import json
import re
import uuid
from typing import Any

from app.llm.base import System, system_text

# Some builds wrap reasoning in tags inside the ordinary content rather than
# putting it in the `thinking` field. Pulled out so it is shown as reasoning
# instead of being read as part of the answer.
THINK_TAG = re.compile(r"<think>(.*?)</think>", re.DOTALL)
OPEN_THINK = re.compile(r"<think>(.*)$", re.DOTALL)


def new_tool_call_id() -> str:
    """An id for a call Ollama did not give us one for."""
    return f"call_{uuid.uuid4().hex[:16]}"


def to_ollama_tools(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Our tool definitions in the OpenAI-style shape Ollama expects."""
    return [
        {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": schema.get("input_schema")
                or {"type": "object", "properties": {}},
            },
        }
        for schema in schemas
    ]


def to_ollama_messages(
    system: System, messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """One thread, translated for /api/chat.

    The thread is walked in order because a tool result only knows the id of
    the call it answers, and the name that call had is needed to label it.

    The system prompt arrives as the content blocks a hosted model needs the
    cache breakpoints on, and is flattened back into the single system message
    Ollama takes. Concatenation, not joining with a separator: the blocks are
    cut out of one continuous document, so putting them back gives the exact
    string this provider sent before the split — which is what keeps a warmed
    KV cache matching the turn it was warmed for.
    """
    translated: list[dict[str, Any]] = []
    text = system_text(system)
    if text:
        translated.append({"role": "system", "content": text})

    names: dict[str, str] = {}  # tool_use id -> tool name

    for message in messages:
        role = message.get("role")
        content = message.get("content")

        if role == "user" and isinstance(content, str):
            translated.append({"role": "user", "content": content})

        elif role == "user" and isinstance(content, list):
            translated.extend(_tool_results(content, names))

        elif role == "assistant" and isinstance(content, list):
            turn = _assistant_turn(content, names)
            if turn is not None:
                translated.append(turn)

        elif role == "assistant" and isinstance(content, str) and content:
            translated.append({"role": "assistant", "content": content})

    return translated


def _assistant_turn(
    blocks: list[Any], names: dict[str, str]
) -> dict[str, Any] | None:
    """One stored assistant message as an Ollama assistant message."""
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")

        if kind == "text":
            text_parts.append(str(block.get("text", "")))

        elif kind == "tool_use":
            name = str(block.get("name", ""))
            names[str(block.get("id", ""))] = name
            tool_calls.append(
                {"function": {"name": name, "arguments": dict(block.get("input") or {})}}
            )

        # Thinking is deliberately not carried back. See the module docstring.

    text = "".join(text_parts).strip()
    if not text and not tool_calls:
        return None

    turn: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_calls:
        turn["tool_calls"] = tool_calls
    return turn


def _tool_results(blocks: list[Any], names: dict[str, str]) -> list[dict[str, Any]]:
    """A batch of tool results as one `tool` message each."""
    produced: list[dict[str, Any]] = []

    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue

        raw = block.get("content")
        text = raw if isinstance(raw, str) else json.dumps(raw, default=str)
        name = names.get(str(block.get("tool_use_id", "")), "")

        produced.append({"role": "tool", "content": text, "tool_name": name})

    return produced


def tool_use_block(name: str, arguments: Any) -> dict[str, Any]:
    """One of Ollama's tool calls as a tool_use block.

    Arguments normally arrive as an object. Some models emit them as a JSON
    string instead, and a couple emit a string that is not JSON at all — which
    is a malformed call, and better handed to the tool registry to refuse
    clearly than dropped here.
    """
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            arguments = {}

    return {
        "type": "tool_use",
        "id": new_tool_call_id(),
        "name": name,
        "input": arguments if isinstance(arguments, dict) else {},
    }


def split_thinking(text: str) -> tuple[str, str]:
    """Separate <think>…</think> from the answer around it.

    Returns (thinking, answer). Only used for models that reason in tags
    rather than in the response's `thinking` field.
    """
    if "<think>" not in text:
        return "", text

    thoughts = THINK_TAG.findall(text)
    answer = THINK_TAG.sub("", text)

    # An unclosed tag means the turn ended mid-thought; the rest is reasoning.
    unclosed = OPEN_THINK.search(answer)
    if unclosed:
        thoughts.append(unclosed.group(1))
        answer = answer[: unclosed.start()]

    return "\n".join(t.strip() for t in thoughts).strip(), answer.strip()
