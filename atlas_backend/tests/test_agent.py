"""The agent loop's obligation to the history it writes.

The assistant message carrying `tool_use` blocks is on disk before any tool
runs. If the matching results never follow it, the API rejects that thread on
every later question — so the results must be written whatever happens.
"""

from types import SimpleNamespace

import pytest

from app.services import agent as agent_module
from app.services.agent import Agent
from app.storage.conversation_repository import Conversation


def _block(tool_use_id, name="get_latest"):
    return {"type": "tool_use", "id": tool_use_id, "name": name, "input": {}}


@pytest.fixture()
def conversation():
    """A thread with no repository behind it — nothing touches the database."""
    return Conversation("conv", "t", 0.0, 0.0)


@pytest.fixture()
def agent():
    """An agent with no provider behind it — no model is ever called."""
    return Agent(provider=None, settings=SimpleNamespace())


def _outcome(monkeypatch, **kwargs):
    outcome = SimpleNamespace(
        content="{}", is_error=False, raw={"data": []}, queries=[], **kwargs
    )
    monkeypatch.setattr(agent_module.registry, "run_tool", lambda *a: outcome)


class TestToolResultsAreAlwaysWritten:
    def test_results_follow_the_calls(self, agent, conversation, monkeypatch):
        _outcome(monkeypatch)

        list(agent._run_tools(conversation, [_block("toolu_1")], []))

        results = conversation.messages[-1]["content"]
        assert [r["tool_use_id"] for r in results] == ["toolu_1"]
        assert results[0]["is_error"] is False

    def test_a_tool_that_raises_still_leaves_a_result(
        self, agent, conversation, monkeypatch
    ):
        def explode(*_):
            raise RuntimeError("influx fell over")

        monkeypatch.setattr(agent_module.registry, "run_tool", explode)

        with pytest.raises(RuntimeError):
            list(agent._run_tools(conversation, [_block("toolu_1")], []))

        results = conversation.messages[-1]["content"]
        assert results[0]["tool_use_id"] == "toolu_1"
        assert results[0]["is_error"] is True

    def test_hanging_up_mid_answer_still_leaves_results(
        self, agent, conversation, monkeypatch
    ):
        """What a client disconnect does to a streaming answer."""
        _outcome(monkeypatch)

        events = agent._run_tools(
            conversation, [_block("toolu_1"), _block("toolu_2")], []
        )
        next(events)  # the first tool_call event, then the reader goes away
        events.close()

        results = conversation.messages[-1]["content"]
        assert [r["tool_use_id"] for r in results] == ["toolu_1", "toolu_2"]
        assert [r["is_error"] for r in results] == [True, True]
