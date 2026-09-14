"""Chat history: it has to survive a restart, and it has to come back intact."""

import pytest

from app.core.errors import ConversationNotFound
from app.storage.conversation_repository import (
    UNTITLED,
    ConversationRepository,
    derive_title,
)


@pytest.fixture()
def repository(temp_database):
    return ConversationRepository()


class TestTitles:
    def test_named_after_the_opening_question(self):
        assert derive_title("What is the CO2 in the test_bench_e?") == (
            "What is the CO2 in the test_bench_e?"
        )

    def test_long_questions_are_cut_on_a_word_boundary(self):
        title = derive_title(
            "What was the average temperature across every room in the habitat "
            "over the last thirty days, broken down by day?"
        )
        assert len(title) <= 61
        assert title.endswith("…")
        assert not title[:-1].endswith(" ")

    def test_whitespace_is_collapsed(self):
        assert derive_title("  what   is\n the   time  ") == "what is the time"

    def test_empty_falls_back(self):
        assert derive_title("   ") == UNTITLED


class TestPersistence:
    def test_a_thread_survives_being_reopened(self, repository):
        conversation = repository.create()
        conversation.append({"role": "user", "content": "hello"})
        conversation.append(
            {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}
        )

        # A fresh repository stands in for a restarted process.
        reloaded = ConversationRepository().get(conversation.id)

        assert len(reloaded.messages) == 2
        assert reloaded.messages[0]["content"] == "hello"
        assert reloaded.messages[1]["content"][0]["text"] == "hi"

    def test_content_blocks_survive_the_round_trip(self, repository):
        """Tool calls must come back exactly, or the model rejects the history."""
        conversation = repository.create()
        conversation.append(
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "hm", "signature": "abc123"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "get_latest",
                        "input": {"measurement": "Temperature"},
                    },
                ],
            }
        )

        blocks = ConversationRepository().get(conversation.id).messages[0]["content"]

        assert blocks[0]["signature"] == "abc123"
        assert blocks[1]["input"] == {"measurement": "Temperature"}

    def test_listing_is_newest_first(self, repository):
        first = repository.create("older")
        second = repository.create("newer")
        second.append({"role": "user", "content": "bump"})

        listed = repository.list()

        assert [row["id"] for row in listed][0] == second.id
        assert {row["id"] for row in listed} == {first.id, second.id}

    def test_listing_counts_messages(self, repository):
        conversation = repository.create()
        for _ in range(3):
            conversation.append({"role": "user", "content": "q"})

        row = next(r for r in repository.list() if r["id"] == conversation.id)
        assert row["message_count"] == 3

    def test_unknown_id_is_a_clear_failure(self, repository):
        with pytest.raises(ConversationNotFound):
            repository.get("never-existed")


class TestDeletion:
    def test_delete_removes_the_thread(self, repository):
        conversation = repository.create()
        conversation.append({"role": "user", "content": "q"})

        assert repository.delete(conversation.id) is True
        with pytest.raises(ConversationNotFound):
            repository.get(conversation.id)

    def test_deleting_twice_is_not_an_error(self, repository):
        conversation = repository.create()
        assert repository.delete(conversation.id) is True
        assert repository.delete(conversation.id) is False

    def test_messages_go_with_their_thread(self, repository):
        conversation = repository.create()
        conversation.append({"role": "user", "content": "q"})
        repository.delete(conversation.id)

        from app.storage.database import connect

        with connect() as connection:
            left = connection.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE conversation_id = ?",
                (conversation.id,),
            ).fetchone()["n"]

        assert left == 0

    def test_delete_all_clears_everything(self, repository):
        repository.create()
        repository.create()

        assert repository.delete_all() == 2
        assert repository.list() == []


class TestContextWindow:
    def test_short_threads_go_up_whole(self, repository):
        conversation = repository.create()
        for _ in range(4):
            conversation.append({"role": "user", "content": "q"})

        assert len(conversation.api_messages(max_turns=10)) == 4

    def test_the_window_opens_on_a_user_message(self, repository):
        """Otherwise the history starts with an orphaned tool_result."""
        conversation = repository.create()
        for _ in range(6):
            conversation.append({"role": "user", "content": "q"})
            conversation.append({"role": "assistant", "content": [{"type": "text"}]})
            conversation.append(
                {"role": "user", "content": [{"type": "tool_result"}]}
            )

        window = conversation.api_messages(max_turns=5)

        assert window[0]["role"] == "user"
        assert isinstance(window[0]["content"], str)

    def test_trimming_never_touches_stored_history(self, repository):
        conversation = repository.create()
        for _ in range(10):
            conversation.append({"role": "user", "content": "q"})

        conversation.api_messages(max_turns=2)

        assert len(ConversationRepository().get(conversation.id).messages) == 10


def _call(tool_use_id):
    return {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": tool_use_id, "name": "get_latest", "input": {}}
        ],
    }


def _answer(tool_use_id):
    return {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": "{}"}
        ],
    }


class TestToolCallPairing:
    """An unanswered tool_use is a 400 the thread never recovers from."""

    def test_a_matched_pair_goes_up_untouched(self, repository):
        conversation = repository.create()
        conversation.append({"role": "user", "content": "q"})
        conversation.append(_call("toolu_1"))
        conversation.append(_answer("toolu_1"))

        assert conversation.api_messages(max_turns=10) == conversation.messages

    def test_a_call_interrupted_before_its_result_is_answered(self, repository):
        """The shape a client disconnect used to leave on disk."""
        conversation = repository.create()
        conversation.append({"role": "user", "content": "q"})
        conversation.append(_call("toolu_1"))
        conversation.append({"role": "user", "content": "still there?"})

        window = conversation.api_messages(max_turns=10)

        answer = window[2]["content"][0]
        assert answer["tool_use_id"] == "toolu_1"
        assert answer["is_error"] is True
        assert window[3]["content"] == "still there?"

    def test_a_call_left_at_the_end_is_answered(self, repository):
        conversation = repository.create()
        conversation.append({"role": "user", "content": "q"})
        conversation.append(_call("toolu_1"))

        window = conversation.api_messages(max_turns=10)

        assert window[-1]["content"][0]["tool_use_id"] == "toolu_1"

    def test_a_half_answered_batch_is_completed(self, repository):
        conversation = repository.create()
        conversation.append({"role": "user", "content": "q"})
        conversation.append(
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "a", "input": {}},
                    {"type": "tool_use", "id": "toolu_2", "name": "b", "input": {}},
                ],
            }
        )
        conversation.append(_answer("toolu_1"))

        results = conversation.api_messages(max_turns=10)[2]["content"]

        assert [r["tool_use_id"] for r in results] == ["toolu_1", "toolu_2"]
        assert results[1]["is_error"] is True

    def test_a_result_answering_nothing_is_dropped(self, repository):
        conversation = repository.create()
        conversation.append({"role": "user", "content": "q"})
        conversation.append(_answer("toolu_gone"))

        assert conversation.api_messages(max_turns=10) == [
            {"role": "user", "content": "q"}
        ]

    def test_pairing_never_touches_stored_history(self, repository):
        conversation = repository.create()
        conversation.append({"role": "user", "content": "q"})
        conversation.append(_call("toolu_1"))

        conversation.api_messages(max_turns=10)

        assert len(ConversationRepository().get(conversation.id).messages) == 2
