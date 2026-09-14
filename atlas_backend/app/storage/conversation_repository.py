"""Reading and writing chat threads.

All SQL lives here. Everything above works in terms of `Conversation` objects
and never sees a cursor.
"""

import json
import time
import uuid
from typing import Any, Optional

from app.core.errors import ConversationNotFound
from app.core.logging import get_logger
from app.storage.database import connect

log = get_logger(__name__)

# A thread gets its name from the question that started it. Long enough to
# tell two threads apart in a sidebar, short enough not to wrap.
TITLE_MAX_CHARS = 60
UNTITLED = "New conversation"


class Conversation:
    """One chat thread.

    `messages` is the full history in Messages API form. Appending writes
    through to disk immediately, so an answer that is interrupted halfway
    still leaves the completed part of the exchange stored.
    """

    def __init__(
        self,
        conversation_id: str,
        title: str,
        created_at: float,
        updated_at: float,
        messages: list[dict[str, Any]] | None = None,
        repository: Optional["ConversationRepository"] = None,
    ) -> None:
        self.id = conversation_id
        self.title = title
        self.created_at = created_at
        self.updated_at = updated_at
        self.messages: list[dict[str, Any]] = messages or []
        self._repository = repository

    def append(self, message: dict[str, Any]) -> None:
        """Add a message to the thread and persist it."""
        position = len(self.messages)
        self.messages.append(message)
        self.updated_at = time.time()

        if self._repository is not None:
            self._repository.append_message(self.id, position, message, self.updated_at)

    def api_messages(self, max_turns: int) -> list[dict[str, Any]]:
        """The tail of the history to send with the next request.

        The whole thread stays on disk; this only bounds what goes up to the
        model. The window always opens on a real question, so the history
        never starts mid-exchange with an orphaned `tool_result` the model
        cannot match to its `tool_use`.

        Note that a `tool_result` batch is also carried on a `user` message —
        checking the role alone is not enough to find a question.

        Every `tool_use` in the window is paired with a `tool_result` before
        the window goes out. A thread that was interrupted mid-query — or one
        stored before the loop guaranteed the pairing — is repaired on the way
        to the model rather than rejected by it.
        """
        return _paired(self._window(max_turns))

    def _window(self, max_turns: int) -> list[dict[str, Any]]:
        """The last `max_turns` messages, cut on a question."""
        if len(self.messages) <= max_turns:
            return self.messages

        start = len(self.messages) - max_turns
        while start < len(self.messages) and not _is_question(self.messages[start]):
            start += 1

        if start >= len(self.messages):
            return self.messages  # no safe cut point; send it all
        return self.messages[start:]


def _is_question(message: dict[str, Any]) -> bool:
    """True for a message someone typed, as opposed to a batch of tool results.

    Both ride on the `user` role; only a question carries plain text.
    """
    return message.get("role") == "user" and isinstance(message.get("content"), str)


# What a tool call that never came back says to the model. It reads as a
# failed query, which the model already knows how to recover from.
LOST_TOOL_RESULT = "This query did not finish and its result was lost."


def unanswered_result(tool_use_id: str) -> dict[str, Any]:
    """A `tool_result` standing in for a call whose real result never arrived."""
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": LOST_TOOL_RESULT,
        "is_error": True,
    }


def _tool_use_ids(message: dict[str, Any]) -> list[str]:
    content = message.get("content")
    if message.get("role") != "assistant" or not isinstance(content, list):
        return []
    return [
        block["id"]
        for block in content
        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id")
    ]


def _is_tool_result(block: Any) -> bool:
    return isinstance(block, dict) and block.get("type") == "tool_result"


def _tool_result_batch(message: dict[str, Any]) -> list[Any] | None:
    """The blocks of a `user` message that answers tool calls, or None."""
    content = message.get("content")
    if message.get("role") != "user" or not isinstance(content, list):
        return None
    if not any(_is_tool_result(block) for block in content):
        return None
    return content


def _paired(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every `tool_use` answered by a `tool_result` in the very next message.

    The API rejects the whole request over a single unmatched pair, and a
    thread that hits that is stuck for good — the bad pair is on disk and goes
    up again with every follow-up. So gaps are filled with a failed result and
    results that answer nothing are dropped. Stored history is not touched.
    """
    paired: list[dict[str, Any]] = []
    pending: list[str] = []  # tool_use ids from the message just added

    for message in messages:
        batch = _tool_result_batch(message)

        if batch is not None:
            kept = [
                block
                for block in batch
                if not _is_tool_result(block) or block.get("tool_use_id") in pending
            ]
            answered = {
                block.get("tool_use_id") for block in kept if _is_tool_result(block)
            }
            kept += [unanswered_result(i) for i in pending if i not in answered]
            pending = []
            if kept:
                paired.append({**message, "content": kept})
            continue

        if pending:
            paired.append(
                {"role": "user", "content": [unanswered_result(i) for i in pending]}
            )

        paired.append(message)
        pending = _tool_use_ids(message)

    if pending:
        paired.append(
            {"role": "user", "content": [unanswered_result(i) for i in pending]}
        )

    return paired


def derive_title(text: str) -> str:
    """A thread's name, taken from the question that opened it."""
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return UNTITLED
    if len(cleaned) <= TITLE_MAX_CHARS:
        return cleaned
    # Cut on a word boundary so the label does not end mid-word.
    clipped = cleaned[:TITLE_MAX_CHARS].rsplit(" ", 1)[0]
    return f"{clipped or cleaned[:TITLE_MAX_CHARS]}…"


class ConversationRepository:
    """Durable chat threads, in SQLite."""

    # -- writing -----------------------------------------------------------

    def create(self, title: str = UNTITLED) -> Conversation:
        conversation = Conversation(
            conversation_id=uuid.uuid4().hex,
            title=title,
            created_at=time.time(),
            updated_at=time.time(),
            repository=self,
        )

        with connect() as connection:
            connection.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    conversation.id,
                    conversation.title,
                    conversation.created_at,
                    conversation.updated_at,
                ),
            )

        log.info("Opened conversation %s", conversation.id)
        return conversation

    def append_message(
        self,
        conversation_id: str,
        position: int,
        message: dict[str, Any],
        updated_at: float,
    ) -> None:
        with connect() as connection:
            connection.execute(
                "INSERT INTO messages "
                "(conversation_id, position, role, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    conversation_id,
                    position,
                    message.get("role", "user"),
                    json.dumps(message.get("content"), default=str),
                    updated_at,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (updated_at, conversation_id),
            )

    def set_title(self, conversation_id: str, title: str) -> None:
        with connect() as connection:
            connection.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (title, conversation_id),
            )

    def title_if_untitled(self, conversation: Conversation, question: str) -> None:
        """Name a thread from its opening question, once."""
        if conversation.title != UNTITLED:
            return
        title = derive_title(question)
        conversation.title = title
        self.set_title(conversation.id, title)

    # -- reading -----------------------------------------------------------

    def get(self, conversation_id: str) -> Conversation:
        with connect() as connection:
            row = connection.execute(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()

            if row is None:
                raise ConversationNotFound(
                    f"Conversation {conversation_id} does not exist. It may have "
                    "been deleted. Start a new one."
                )

            message_rows = connection.execute(
                "SELECT role, content FROM messages "
                "WHERE conversation_id = ? ORDER BY position ASC",
                (conversation_id,),
            ).fetchall()

        messages = [
            {"role": message["role"], "content": json.loads(message["content"])}
            for message in message_rows
        ]

        return Conversation(
            conversation_id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            messages=messages,
            repository=self,
        )

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        """Thread summaries, newest activity first."""
        with connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.title, c.created_at, c.updated_at,
                       COUNT(m.id) AS message_count
                  FROM conversations c
                  LEFT JOIN messages m ON m.conversation_id = c.id
                 GROUP BY c.id
                 ORDER BY c.updated_at DESC
                 LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]

    # -- deleting ----------------------------------------------------------

    def delete(self, conversation_id: str) -> bool:
        """Remove a thread and its messages. True if there was one to remove."""
        with connect() as connection:
            cursor = connection.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
            # The messages go with it via ON DELETE CASCADE.
            removed = cursor.rowcount > 0

        if removed:
            log.info("Deleted conversation %s", conversation_id)
        return removed

    def delete_all(self) -> int:
        """Remove every thread. Returns how many were removed."""
        with connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM conversations"
            ).fetchone()["n"]
            connection.execute("DELETE FROM conversations")

        log.info("Deleted all %d conversation(s)", count)
        return count


_repository: ConversationRepository | None = None


def get_repository() -> ConversationRepository:
    """The process-wide repository."""
    global _repository
    if _repository is None:
        _repository = ConversationRepository()
    return _repository
