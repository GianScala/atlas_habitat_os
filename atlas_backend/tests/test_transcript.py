"""Reopening a thread must look like having watched it arrive.

The stored history is Messages API shaped — assistant blocks, tool_result
blocks wrapped in user messages. These tests pin the projection back into
something a person reads.
"""

import json

from app.services.transcript import to_transcript


def tool_result(tool_use_id: str, payload: dict, is_error: bool = False) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(payload),
        "is_error": is_error,
    }


class TestBasics:
    def test_empty_history(self):
        assert to_transcript([]) == []

    def test_a_plain_exchange(self):
        transcript = to_transcript(
            [
                {"role": "user", "content": "how warm is it?"},
                {"role": "assistant", "content": [{"type": "text", "text": "21 °C."}]},
            ]
        )

        assert [m.role for m in transcript] == ["user", "assistant"]
        assert transcript[0].content == "how warm is it?"
        assert transcript[1].content == "21 °C."

    def test_thinking_is_kept_separate_from_the_answer(self):
        transcript = to_transcript(
            [
                {"role": "user", "content": "q"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "considering"},
                        {"type": "text", "text": "answer"},
                    ],
                },
            ]
        )

        assert transcript[1].thinking == "considering"
        assert transcript[1].content == "answer"


class TestToolRounds:
    def _history(self, payload: dict, is_error: bool = False) -> list[dict]:
        return [
            {"role": "user", "content": "how warm is it?"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me check."},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "get_latest",
                        "input": {"measurement": "Temperature"},
                    },
                ],
            },
            {"role": "user", "content": [tool_result("toolu_1", payload, is_error)]},
            {"role": "assistant", "content": [{"type": "text", "text": "It is 21 °C."}]},
        ]

    def test_several_rounds_become_one_bubble(self):
        transcript = to_transcript(
            self._history({"query": "SELECT 1", "data": {"value": 21}})
        )

        # user, then a single assistant turn — not one per round trip.
        assert [m.role for m in transcript] == ["user", "assistant"]

    def test_text_from_before_and_after_a_query_is_separated(self):
        transcript = to_transcript(
            self._history({"query": "SELECT 1", "data": {"value": 21}})
        )

        assert transcript[1].content == "Let me check.\n\nIt is 21 °C."

    def test_a_query_that_returned_data_reads_as_ok(self):
        transcript = to_transcript(
            self._history({"query": "SELECT 1", "data": {"value": 21}})
        )
        step = transcript[1].trace[0]

        assert step.status == "ok"
        assert step.name == "get_latest"
        assert step.input == {"measurement": "Temperature"}
        assert step.queries == ["SELECT 1"]

    def test_a_query_that_found_nothing_reads_as_empty(self):
        transcript = to_transcript(self._history({"query": "SELECT 1", "data": None}))
        assert transcript[1].trace[0].status == "empty"

    def test_a_failed_query_keeps_its_reason(self):
        history = self._history({}, is_error=True)
        history[2]["content"][0]["content"] = "Query failed: HTTP 401"

        step = to_transcript(history)[1].trace[0]

        assert step.status == "failed"
        assert "401" in (step.detail or "")

    def test_sources_are_collected_for_the_footer(self):
        transcript = to_transcript(
            self._history({"queries": ["SELECT a", "SELECT b"], "data": [1]})
        )
        assert transcript[1].sources == ["SELECT a", "SELECT b"]

    def test_sources_are_deduplicated(self):
        history = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "a", "name": "t", "input": {}},
                    {"type": "tool_use", "id": "b", "name": "t", "input": {}},
                ],
            },
            {
                "role": "user",
                "content": [
                    tool_result("a", {"query": "SELECT same", "data": [1]}),
                    tool_result("b", {"query": "SELECT same", "data": [1]}),
                ],
            },
            {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        ]

        assert to_transcript(history)[1].sources == ["SELECT same"]


class TestRobustness:
    def test_a_result_with_no_matching_call_is_ignored(self):
        history = [
            {"role": "user", "content": "q"},
            {"role": "user", "content": [tool_result("orphan", {"data": 1})]},
        ]
        assert len(to_transcript(history)) == 1

    def test_unparseable_tool_output_does_not_break_the_page(self):
        history = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "a", "name": "t", "input": {}}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "a", "content": "not json"}
                ],
            },
        ]

        step = to_transcript(history)[1].trace[0]
        assert step.status == "empty"
        assert step.queries == []

    def test_two_separate_questions_stay_separate(self):
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": [{"type": "text", "text": "one"}]},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": [{"type": "text", "text": "two"}]},
        ]

        assert [m.role for m in to_transcript(history)] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
