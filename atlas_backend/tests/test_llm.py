"""Running a model on this machine.

Two things are worth pinning down here. First the translation: a thread
written by one model has to be readable by another, and the shape it is
stored in is not the shape Ollama wants. Second the reasoning split: models
that have no `thinking` field write <think> tags into the content instead, and
those tags arrive cut in half across streaming chunks.
"""

import copy
import threading
from unittest import mock

import pytest

from app.core.errors import ModelError
from app.llm import anthropic_provider, providers, selection, translate
from app.llm.ollama_provider import OllamaProvider, ThinkStream
from app.schemas.chat import TextDeltaEvent, ThinkingDeltaEvent
from app.services import prompt

# A thread in the shape the database keeps: one question, an assistant turn
# that thought, spoke and called a tool, and the result of that call.
THREAD = [
    {"role": "user", "content": "How warm is the atrium?"},
    {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "Temperature, probably.", "signature": "x"},
            {"type": "text", "text": "Let me look."},
            {
                "type": "tool_use",
                "id": "call_1",
                "name": "get_latest",
                "input": {"measurement": "Temperature", "location": "Atrium"},
            },
        ],
    },
    {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "call_1",
                "content": '{"data": 21.4}',
                "is_error": False,
            }
        ],
    },
]


class TestTranslatingAThread:
    def test_every_message_finds_its_role(self):
        translated = translate.to_ollama_messages("You are ATLAS.", THREAD)

        assert [m["role"] for m in translated] == [
            "system",
            "user",
            "assistant",
            "tool",
        ]

    def test_a_tool_call_carries_its_arguments(self):
        assistant = translate.to_ollama_messages("", THREAD)[1]

        assert assistant["content"] == "Let me look."
        assert assistant["tool_calls"] == [
            {
                "function": {
                    "name": "get_latest",
                    "arguments": {"measurement": "Temperature", "location": "Atrium"},
                }
            }
        ]

    def test_a_result_is_labelled_with_the_tool_it_answers(self):
        """Ollama matches results to calls by name, not by id."""
        result = translate.to_ollama_messages("", THREAD)[2]

        assert result["tool_name"] == "get_latest"
        assert result["content"] == '{"data": 21.4}'

    def test_reasoning_is_not_sent_back(self):
        """These models are trained on threads where only the answer survives."""
        translated = translate.to_ollama_messages("", THREAD)

        assert all("thinking" not in message for message in translated)
        assert "probably" not in translated[1]["content"]

    def test_an_assistant_turn_with_nothing_in_it_is_dropped(self):
        empty = [{"role": "assistant", "content": [{"type": "thinking", "thinking": "…"}]}]

        assert translate.to_ollama_messages("", empty) == []

    def test_tools_are_described_the_way_ollama_asks(self):
        [tool] = translate.to_ollama_tools(
            [
                {
                    "name": "get_latest",
                    "description": "The most recent reading.",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ]
        )

        assert tool["type"] == "function"
        assert tool["function"]["name"] == "get_latest"
        assert tool["function"]["parameters"] == {"type": "object", "properties": {}}


class TestToolArguments:
    def test_an_object_is_used_as_it_stands(self):
        block = translate.tool_use_block("get_latest", {"measurement": "Water"})

        assert block["input"] == {"measurement": "Water"}
        assert block["id"].startswith("call_")

    def test_arguments_that_arrive_as_json_text_are_parsed(self):
        """Some models emit the object as a string. It means the same thing."""
        block = translate.tool_use_block("get_latest", '{"measurement": "Water"}')

        assert block["input"] == {"measurement": "Water"}

    def test_arguments_that_are_not_json_at_all_become_empty(self):
        """A malformed call the registry can refuse clearly, rather than a crash."""
        block = translate.tool_use_block("get_latest", "measurement=Water")

        assert block["input"] == {}


class TestSplittingOutReasoning:
    def test_thinking_and_answer_land_on_separate_channels(self):
        stream = ThinkStream()

        assert stream.feed("<think>Checking.</think>It is 21.4 C.") == [
            ("thinking", "Checking."),
            ("text", "It is 21.4 C."),
        ]

    def test_a_tag_split_across_chunks_is_still_a_tag(self):
        """`<thi` at the end of one chunk and `nk>` at the start of the next."""
        stream = ThinkStream()

        first = stream.feed("Hello <thi")
        second = stream.feed("nk>quiet</think> there")

        assert first == [("text", "Hello ")]
        assert second == [("thinking", "quiet"), ("text", " there")]

    def test_text_with_no_tags_passes_straight_through(self):
        stream = ThinkStream()

        assert stream.feed("It is 21.4 C.") == [("text", "It is 21.4 C.")]
        assert stream.flush() == []

    def test_reasoning_is_shown_as_it_arrives_not_held_to_the_end(self):
        """An open tag with no close yet is still reasoning, and still shown."""
        stream = ThinkStream()

        assert stream.feed("<think>I was saying") == [("thinking", "I was saying")]
        assert stream.flush() == []

    def test_a_half_written_tag_is_held_back_until_it_is_settled(self):
        """`</th` might become a close tag, so it is not shown as an answer yet."""
        stream = ThinkStream()

        assert stream.feed("<think>done</th") == [("thinking", "done")]
        assert stream.feed("ink>21.4 C.") == [("text", "21.4 C.")]


class FakeClient:
    """An Ollama daemon that says whatever the test tells it to."""

    def __init__(self, chunks, fail_on_think=False):
        self.chunks = chunks
        self.fail_on_think = fail_on_think
        self.payloads = []

    def chat(self, payload):
        # Copied: the provider drops `think` from the very dict it passed in
        # when it retries, and a test that held the reference would see only
        # the retry.
        self.payloads.append(dict(payload))
        if self.fail_on_think and "think" in payload:
            raise ModelError('"qwen" does not support thinking', kind="ollama")
        return iter(self.chunks)

    def chat_once(self, payload):
        self.payloads.append(dict(payload))
        if self.fail_on_think and "think" in payload:
            raise ModelError('"qwen" does not support thinking', kind="ollama")
        return {"message": {"content": ""}, "done": True}


def _provider(chunks, **kwargs):
    provider = OllamaProvider(model="qwen3:8b")
    provider.client = FakeClient(chunks, **kwargs)
    return provider


def _drain(generator):
    """Run a generator to completion, returning (events, return value)."""
    events = []
    try:
        while True:
            events.append(next(generator))
    except StopIteration as stop:
        return events, stop.value


class TestOneLocalTurn:
    def test_text_streams_and_ends_as_one_block(self):
        events, turn = _drain(
            _provider(
                [
                    {"message": {"content": "It is "}},
                    {"message": {"content": "21.4 C."}},
                    {"message": {"content": ""}, "done": True, "done_reason": "stop"},
                ]
            ).stream(messages=[], system="", tools=[])
        )

        assert [e.text for e in events if isinstance(e, TextDeltaEvent)] == [
            "It is ",
            "21.4 C.",
        ]
        assert turn.content == [{"type": "text", "text": "It is 21.4 C."}]
        assert turn.stop_reason == "end_turn"

    def test_a_tool_call_comes_back_as_a_tool_use_block(self):
        _, turn = _drain(
            _provider(
                [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "get_latest",
                                        "arguments": {"measurement": "Water"},
                                    }
                                }
                            ],
                        },
                        "done": True,
                        "done_reason": "stop",
                    }
                ]
            ).stream(messages=[], system="", tools=[])
        )

        [call] = turn.tool_uses
        assert call["name"] == "get_latest"
        assert call["input"] == {"measurement": "Water"}
        assert turn.stop_reason == "tool_use"

    def test_the_thinking_field_becomes_thinking_events(self):
        events, turn = _drain(
            _provider(
                [
                    {"message": {"thinking": "Which tank?"}},
                    {"message": {"content": "The clean one."}, "done": True},
                ]
            ).stream(messages=[], system="", tools=[])
        )

        assert [e.text for e in events if isinstance(e, ThinkingDeltaEvent)] == [
            "Which tank?"
        ]
        # Kept in the stored turn so a reopened thread still shows the
        # working, even though it is never sent back to the model.
        assert turn.content == [
            {"type": "thinking", "thinking": "Which tank?"},
            {"type": "text", "text": "The clean one."},
        ]

    def test_a_turn_that_only_thought_has_not_answered(self):
        """The agent needs to tell reasoning apart from an answer."""
        from app.services.agent import _said_anything

        _, turn = _drain(
            _provider([{"message": {"thinking": "Hmm."}, "done": True}]).stream(
                messages=[], system="", tools=[]
            )
        )

        assert turn.content == [{"type": "thinking", "thinking": "Hmm."}]
        assert _said_anything(turn) is False

    def test_a_model_that_cannot_think_is_asked_again_without_it(self):
        provider = _provider([{"message": {"content": "Fine."}, "done": True}],
                             fail_on_think=True)

        _, turn = _drain(provider.stream(messages=[], system="", tools=[]))

        assert [("think" in p) for p in provider.client.payloads] == [True, False]
        assert turn.content == [{"type": "text", "text": "Fine."}]

    def test_turning_thinking_off_says_so_rather_than_staying_quiet(self, monkeypatch):
        """Qwen3 reasons by default: omitting the field leaves it on."""
        provider = _provider([{"message": {"content": "21.4 C."}, "done": True}])
        # Settings are a process-wide singleton; monkeypatch puts it back.
        monkeypatch.setattr(provider.settings, "ollama_thinking", "disabled")

        _drain(provider.stream(messages=[], system="", tools=[]))

        assert provider.client.payloads[0]["think"] is False

    def test_a_cut_off_answer_says_so(self):
        _, turn = _drain(
            _provider(
                [{"message": {"content": "It is 21"}, "done": True, "done_reason": "length"}]
            ).stream(messages=[], system="", tools=[])
        )

        assert turn.stop_reason == "max_tokens"


class TestWarmingTheCache:
    """Prefilling the prompt prefix while nobody is waiting for an answer.

    The warm-up is worth exactly as much as the prefix it sends is identical
    to the one a real turn sends. If they ever drift, it still succeeds, still
    logs a cheerful line, and warms tokens nobody will ask for — so the drift
    is what these tests are really watching.
    """

    SYSTEM = "You are ATLAS."
    TOOLS = [{"name": "get_latest", "description": "x", "input_schema": {}}]

    @pytest.fixture(autouse=True)
    def _no_state_between_tests(self):
        """The gate is module-level, so one test's claim would leak into the next."""
        from app.llm import warm as warming

        yield
        warming._in_flight = None
        warming._answering = 0

    def test_it_sends_the_prefix_a_real_turn_would_send(self):
        provider = _provider([{"message": {"content": "hi"}, "done": True}])

        _drain(provider.stream(messages=[], system=self.SYSTEM, tools=self.TOOLS))
        provider.prewarm(self.SYSTEM, self.TOOLS)
        turn, warm = provider.client.payloads

        assert warm["messages"][0] == turn["messages"][0]  # the system message
        assert warm["tools"] == turn["tools"]
        assert warm["model"] == turn["model"]
        assert warm["think"] == turn["think"]

    def test_the_options_match_so_ollama_keeps_one_runner(self):
        """Differing options start a fresh runner and drop the cache just filled."""
        provider = _provider([{"message": {"content": "hi"}, "done": True}])

        _drain(provider.stream(messages=[], system=self.SYSTEM, tools=self.TOOLS))
        provider.prewarm(self.SYSTEM, self.TOOLS)
        turn, warm = provider.client.payloads

        assert warm["options"]["num_ctx"] == turn["options"]["num_ctx"]
        assert warm["options"]["temperature"] == turn["options"]["temperature"]
        assert warm["keep_alive"] == turn["keep_alive"]

    def test_it_asks_for_one_token_and_no_more(self):
        """The prefill is the point; generating an answer nobody reads is not."""
        provider = _provider([])

        provider.prewarm(self.SYSTEM, self.TOOLS)

        assert provider.client.payloads[0]["options"]["num_predict"] == 1

    def test_a_model_that_cannot_think_is_still_warmed(self):
        """Giving up here would leave that model paying in full on question one."""
        provider = _provider([], fail_on_think=True)

        provider.prewarm(self.SYSTEM, self.TOOLS)

        assert [("think" in p) for p in provider.client.payloads] == [True, False]

    def test_a_hosted_model_has_nothing_on_this_machine_to_warm(self, temp_database):
        from app.llm import warm as warming

        selection.choose("anthropic", "claude-opus-5")

        assert warming.warm() is None

    def test_switching_twice_does_not_queue_two_warm_ups(self, temp_database, monkeypatch):
        from app.llm import warm as warming

        selection.choose("ollama", "qwen3:8b")
        started = threading.Event()
        release = threading.Event()

        def slow_warm(key):
            started.set()
            release.wait(5)

        monkeypatch.setattr(warming, "_run", slow_warm)

        first = warming.warm()
        assert started.wait(5)
        second = warming.warm()
        release.set()
        first.join(5)

        assert second is None

    def test_no_warm_up_starts_while_a_question_is_being_answered(self, temp_database):
        from app.llm import warm as warming

        selection.choose("ollama", "qwen3:8b")

        with warming.priority():
            assert warming.warm() is None

    def test_the_runner_comes_back_only_when_the_last_answer_is_done(self, temp_database):
        """Two overlapping questions: the first to finish must not hand it back."""
        from app.llm import warm as warming

        selection.choose("ollama", "qwen3:8b")
        provider = _provider([])

        with mock.patch.object(providers, "build", return_value=provider):
            with warming.priority():
                with warming.priority():
                    pass
                assert warming.warm() is None

            released = warming.warm()
            assert released is not None
            released.join(5)

    def test_a_runtime_that_is_down_is_not_an_error(self, temp_database, monkeypatch):
        """The first question discovers it anyway, and says so properly."""
        from app.llm import providers
        from app.llm import warm as warming

        selection.choose("ollama", "qwen3:8b")

        def refuse(choice):
            raise ModelError("Could not reach Ollama", kind="ollama_offline")

        monkeypatch.setattr(providers, "build", refuse)

        thread = warming.warm()
        thread.join(5)

        assert not thread.is_alive()


class TestWhichModelAnswers:
    def test_nothing_chosen_falls_back_to_the_configuration(self, temp_database):
        from app.config import get_settings

        settings = get_settings()
        choice = selection.active(settings)

        assert choice.provider == settings.llm_provider
        assert choice.local is (choice.provider == "ollama")

    def test_a_choice_outlives_the_call_that_made_it(self, temp_database):
        selection.choose("ollama", "mistral-nemo")

        assert selection.active() == selection.Choice("ollama", "mistral-nemo")

    def test_each_provider_remembers_its_own_model(self, temp_database):
        """Trying the cloud and switching back should not lose the local choice."""
        selection.choose("ollama", "mistral-nemo")
        selection.choose("anthropic", "claude-opus-5")

        assert selection.active().model == "claude-opus-5"

        assert selection.choose("ollama").model == "mistral-nemo"

    def test_the_implied_latest_tag_is_not_part_of_the_name(self):
        """`mistral-nemo` and `mistral-nemo:latest` are one model, not two."""
        from app.llm.catalogue import canonical

        assert canonical("mistral-nemo:latest") == "mistral-nemo"
        assert canonical("qwen3:8b") == "qwen3:8b"

    def test_an_unknown_provider_is_refused(self, temp_database):
        from app.core.errors import QueryError

        with pytest.raises(QueryError):
            selection.choose("openai", "gpt-4")


class TestTheCachedPrefix:
    """The breakpoints that stop a hosted model re-reading the same prefix.

    Every round of a turn re-sends the rules, the fourteen-odd tool schemas and
    everything the earlier rounds produced. Marked, the cloud reads that back
    instead of processing it again; unmarked, a five-round answer pays for it
    five times.

    What makes this worth a test is that getting it wrong is invisible. A
    breakpoint in the wrong place, or a prefix that quietly varies, costs money
    and seconds and changes no answer, so nothing else in this suite would ever
    notice.
    """

    def test_the_thread_is_marked_at_its_end(self):
        """So the next round reads this round rather than repeating it."""
        marked = anthropic_provider._cached_tail(copy.deepcopy(THREAD))

        assert marked[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}

    def test_only_the_end_is_marked(self):
        """There are four breakpoints to spend per request and two other uses."""
        marked = anthropic_provider._cached_tail(copy.deepcopy(THREAD))

        earlier = [
            block
            for message in marked[:-1]
            for block in message["content"]
            if isinstance(block, dict)
        ]
        assert not any("cache_control" in block for block in earlier)

    def test_the_stored_thread_is_left_alone(self):
        """`messages` is the conversation's own list of the dicts it persists.

        Marking them in place would write a breakpoint onto the thread on disk,
        and send it back — in the wrong place — on every round after this one.
        """
        thread = copy.deepcopy(THREAD)
        untouched = copy.deepcopy(thread)

        anthropic_provider._cached_tail(thread)

        assert thread == untouched

    def test_a_typed_question_can_carry_a_breakpoint_too(self):
        """A question is stored as a bare string, which has nowhere to put one."""
        marked = anthropic_provider._cached_tail([{"role": "user", "content": "hi"}])

        assert marked[0]["content"] == [
            {"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}
        ]

    def test_an_empty_thread_is_not_a_failure(self):
        assert anthropic_provider._cached_tail([]) == []

    def test_the_frozen_half_of_the_prompt_is_the_marked_half(self, temp_database):
        """And the half that a crew member can edit is the unmarked one.

        The order is what makes the split worth anything: tools render before
        system, so the breakpoint on the first block covers the schemas as
        well, and changing the answering style invalidates only what follows.
        """
        blocks = prompt.system_prompt(_Hosted())

        assert blocks[0]["cache_control"] == {"type": "ephemeral"}
        assert prompt.SYSTEM_PROMPT in blocks[0]["text"]
        assert all("cache_control" not in block for block in blocks[1:])

    def test_the_style_lands_after_the_breakpoint(self, temp_database):
        """Where changing it costs a few hundred tokens instead of six thousand."""
        blocks = prompt.system_prompt(_Hosted())

        assert "How to say it" in "".join(block["text"] for block in blocks[1:])

    def test_no_empty_block_is_sent(self, temp_database):
        """The API refuses one, and an unmissioned habitat can produce it."""
        with mock.patch.object(prompt, "_style", return_value=""), mock.patch.object(
            prompt, "_mission", return_value=""
        ):
            blocks = prompt.system_prompt(_Hosted())

        assert [block["text"] for block in blocks] == [blocks[0]["text"]]
        assert blocks[0]["text"].strip()

    def test_a_local_model_still_gets_one_string(self, temp_database):
        """It reads a system message, not content blocks. The split is invisible."""
        blocks = prompt.system_prompt(_Local())

        flattened = translate.to_ollama_messages(blocks, [])[0]

        assert flattened["content"] == "".join(b["text"] for b in blocks)

    def test_the_warm_up_and_the_turn_agree_on_that_string(self, temp_database):
        """A warmed KV cache only helps a turn whose prefix matches it byte for byte."""
        blocks = prompt.system_prompt(_Local())
        text = "".join(block["text"] for block in blocks)

        assert translate.to_ollama_messages(blocks, []) == translate.to_ollama_messages(
            text, []
        )


class _Hosted:
    local = False


class _Local:
    local = True
