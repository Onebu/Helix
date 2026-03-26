"""Tests for SynthesisEngine: conversation simulation, tool interception, scoring, persistence.

Covers requirements:
- SYNTH-02: Multi-turn conversation simulation with persona/target alternation
- SYNTH-03: Tool call interception via MockMatcher
- SYNTH-04: Conversation scoring via BehaviorJudgeScorer
- SYNTH-05: Only failing conversations persisted as TestCases
- SYNTH-06: Persona uses META model, target uses TARGET model
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from api.dataset.models import TestCase
from api.evaluation.models import CaseResult
from api.registry.schemas import MockDefinition, MockScenario
from api.synthesis.engine import SynthesisEngine
from api.synthesis.models import (
    ConversationRecord,
    PersonaProfile,
    SynthesisConfig,
)
from api.types import LLMResponse, ModelRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_response(
    content: str | None = "response",
    tool_calls: list[dict] | None = None,
    role: ModelRole = ModelRole.TARGET,
) -> LLMResponse:
    """Create a minimal LLMResponse for testing."""
    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        model_used="test-model",
        role=role,
        input_tokens=10,
        output_tokens=10,
        cost_usd=0.001,
        timestamp=datetime.now(),
    )


def _make_persona(**overrides: Any) -> PersonaProfile:
    """Create a test persona with sensible defaults."""
    defaults = {
        "id": "test-persona",
        "role": "Test user",
        "traits": ["direct"],
        "communication_style": "concise",
        "goal": "Test the assistant",
        "edge_cases": ["edge1"],
        "behavior_criteria": ["The assistant should respond appropriately"],
    }
    defaults.update(overrides)
    return PersonaProfile(**defaults)


def _make_engine(
    meta_responses: list[LLMResponse] | None = None,
    target_responses: list[LLMResponse] | None = None,
    scorer_result: CaseResult | None = None,
    dataset_service: AsyncMock | None = None,
    event_callback: AsyncMock | None = None,
) -> tuple[SynthesisEngine, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """Build a SynthesisEngine with mocked providers.

    Returns (engine, meta_provider, target_provider, judge_scorer, dataset_service).
    """
    meta_provider = AsyncMock()
    target_provider = AsyncMock()
    judge_scorer = AsyncMock()
    ds = dataset_service or AsyncMock()

    if meta_responses:
        meta_provider.chat_completion.side_effect = meta_responses
    if target_responses:
        target_provider.chat_completion.side_effect = target_responses
    if scorer_result:
        judge_scorer.score.return_value = scorer_result

    engine = SynthesisEngine(
        meta_provider=meta_provider,
        target_provider=target_provider,
        judge_scorer=judge_scorer,
        dataset_service=ds,
        meta_model="meta-model",
        target_model="target-model",
        event_callback=event_callback,
    )
    return engine, meta_provider, target_provider, judge_scorer, ds


# ===========================================================================
# TestConversationLoop
# ===========================================================================


class TestConversationLoop:
    """Tests for simulate_conversation: turn alternation, [END] token, max_turns."""

    @pytest.mark.asyncio
    async def test_basic_multi_turn(self) -> None:
        """Persona and target alternate for multiple turns."""
        meta_responses = [
            _make_llm_response("Hello, I need help", role=ModelRole.META),
            _make_llm_response("Can you clarify? [END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response("Sure, how can I help?", role=ModelRole.TARGET),
        ]
        engine, _, _, _, _ = _make_engine(meta_responses, target_responses)
        persona = _make_persona()

        record = await engine.simulate_conversation(
            persona=persona,
            prompt_template="You are a helpful assistant.",
            variables={},
            tools=None,
            mocks=None,
            max_turns=5,
        )

        assert isinstance(record, ConversationRecord)
        assert record.persona_id == "test-persona"
        # Turn 1: user + assistant. Turn 2: persona sends [END] with text
        assert len([m for m in record.chat_history if m["role"] == "user"]) >= 1
        assert record.turns >= 1

    @pytest.mark.asyncio
    async def test_end_token_stops_conversation(self) -> None:
        """Conversation ends when persona sends [END] token."""
        meta_responses = [
            _make_llm_response("Thanks, that's all I need. [END]", role=ModelRole.META),
        ]
        # No target responses needed -- persona ends immediately
        engine, _, _, _, _ = _make_engine(meta_responses, [])
        persona = _make_persona()

        record = await engine.simulate_conversation(
            persona=persona,
            prompt_template="You are a helpful assistant.",
            variables={},
            tools=None,
            mocks=None,
            max_turns=10,
        )

        # Persona ended with [END], text before [END] should be included
        user_msgs = [m for m in record.chat_history if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert "[END]" not in user_msgs[0]["content"]
        assert "Thanks, that's all I need." in user_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_end_token_only_no_text(self) -> None:
        """If persona sends only [END] with no other text, no user message added."""
        meta_responses = [
            _make_llm_response("First message", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response("I can help with that.", role=ModelRole.TARGET),
        ]
        engine, _, _, _, _ = _make_engine(meta_responses, target_responses)
        persona = _make_persona()

        record = await engine.simulate_conversation(
            persona=persona,
            prompt_template="You are a helpful assistant.",
            variables={},
            tools=None,
            mocks=None,
            max_turns=10,
        )

        # One user message from turn 1 + one assistant, then [END] with no text
        user_msgs = [m for m in record.chat_history if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "First message"

    @pytest.mark.asyncio
    async def test_max_turns_truncation(self) -> None:
        """Conversation stops at max_turns even without [END]."""
        # Provide enough responses for 3 turns
        meta_responses = [
            _make_llm_response(f"Turn {i + 1} message", role=ModelRole.META) for i in range(3)
        ]
        target_responses = [
            _make_llm_response(f"Response {i + 1}", role=ModelRole.TARGET) for i in range(3)
        ]
        engine, _, _, _, _ = _make_engine(meta_responses, target_responses)
        persona = _make_persona()

        record = await engine.simulate_conversation(
            persona=persona,
            prompt_template="You are a helpful assistant.",
            variables={},
            tools=None,
            mocks=None,
            max_turns=3,
        )

        user_msgs = [m for m in record.chat_history if m["role"] == "user"]
        assert len(user_msgs) == 3
        assert record.turns == 3

    @pytest.mark.asyncio
    async def test_persona_perspective_reversed(self) -> None:
        """Persona sees its messages as 'assistant' and target's as 'user'."""
        meta_responses = [
            _make_llm_response("Hi there", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response("Hello!", role=ModelRole.TARGET),
        ]
        engine, meta_provider, _, _, _ = _make_engine(meta_responses, target_responses)
        persona = _make_persona()

        await engine.simulate_conversation(
            persona=persona,
            prompt_template="You are a helpful assistant.",
            variables={},
            tools=None,
            mocks=None,
        )

        # Check what messages were passed to persona (meta) on second call
        assert meta_provider.chat_completion.call_count == 2
        second_call_messages = meta_provider.chat_completion.call_args_list[1].kwargs.get(
            "messages",
            meta_provider.chat_completion.call_args_list[1][0][0]
            if meta_provider.chat_completion.call_args_list[1][0]
            else [],
        )
        # Persona should see its own message as "assistant" and target's as "user"
        non_system = [m for m in second_call_messages if m["role"] != "system"]
        assert any(m["role"] == "assistant" and m["content"] == "Hi there" for m in non_system)
        assert any(m["role"] == "user" and m["content"] == "Hello!" for m in non_system)


# ===========================================================================
# TestToolCallInterception
# ===========================================================================


class TestToolCallInterception:
    """Tests for tool call handling via MockMatcher during simulation."""

    @pytest.mark.asyncio
    async def test_tool_calls_resolved_via_mock_matcher(self) -> None:
        """Target tool calls are intercepted by MockMatcher and mock responses injected."""
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city": "London"}'},
        }
        meta_responses = [
            _make_llm_response("What's the weather?", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            # First: tool call response
            _make_llm_response(content=None, tool_calls=[tool_call], role=ModelRole.TARGET),
            # Second: after seeing tool results, target gives text response
            _make_llm_response("The weather in London is sunny.", role=ModelRole.TARGET),
        ]

        mocks = [
            MockDefinition(
                tool_name="get_weather",
                scenarios=[
                    MockScenario(
                        match_args={"city": "London"},
                        response="Sunny, 22C",
                    )
                ],
            )
        ]

        engine, _, _, _, _ = _make_engine(meta_responses, target_responses)
        persona = _make_persona()

        record = await engine.simulate_conversation(
            persona=persona,
            prompt_template="You are a weather assistant.",
            variables={},
            tools=[{"type": "function", "function": {"name": "get_weather"}}],
            mocks=mocks,
            max_turns=5,
        )

        # History should contain: user, assistant (tool_calls), tool (result), assistant (text)
        roles = [m["role"] for m in record.chat_history]
        assert "tool" in roles
        tool_msg = next(m for m in record.chat_history if m["role"] == "tool")
        assert "Sunny, 22C" in tool_msg["content"]

    @pytest.mark.asyncio
    async def test_unmatched_tool_call_gets_fallback(self) -> None:
        """Tool calls without matching mock get 'No mock available' fallback."""
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "unknown_tool", "arguments": "{}"},
        }
        meta_responses = [
            _make_llm_response("Do something", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response(content=None, tool_calls=[tool_call], role=ModelRole.TARGET),
            _make_llm_response("I tried but couldn't.", role=ModelRole.TARGET),
        ]

        engine, _, _, _, _ = _make_engine(meta_responses, target_responses)
        persona = _make_persona()

        record = await engine.simulate_conversation(
            persona=persona,
            prompt_template="You are an assistant.",
            variables={},
            tools=[{"type": "function", "function": {"name": "unknown_tool"}}],
            mocks=[],  # No mocks defined
            max_turns=5,
        )

        tool_msg = next(m for m in record.chat_history if m["role"] == "tool")
        assert "No mock configured" in tool_msg["content"]

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_one_turn(self) -> None:
        """Multiple tool calls in a single target response are all resolved."""
        tool_calls = [
            {"id": "call_1", "type": "function", "function": {"name": "get_a", "arguments": "{}"}},
            {"id": "call_2", "type": "function", "function": {"name": "get_b", "arguments": "{}"}},
        ]
        meta_responses = [
            _make_llm_response("Get both A and B", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response(content=None, tool_calls=tool_calls, role=ModelRole.TARGET),
            _make_llm_response("Got both results.", role=ModelRole.TARGET),
        ]
        mocks = [
            MockDefinition(
                tool_name="get_a", scenarios=[MockScenario(match_args={}, response="Result A")]
            ),
            MockDefinition(
                tool_name="get_b", scenarios=[MockScenario(match_args={}, response="Result B")]
            ),
        ]

        engine, _, _, _, _ = _make_engine(meta_responses, target_responses)
        persona = _make_persona()

        record = await engine.simulate_conversation(
            persona=persona,
            prompt_template="You are an assistant.",
            variables={},
            tools=[],
            mocks=mocks,
            max_turns=5,
        )

        tool_msgs = [m for m in record.chat_history if m["role"] == "tool"]
        assert len(tool_msgs) == 2
        contents = {m["content"] for m in tool_msgs}
        assert "Result A" in contents
        assert "Result B" in contents


# ===========================================================================
# TestConversationScoring
# ===========================================================================


class TestConversationScoring:
    """Tests for scoring conversations via BehaviorJudgeScorer in run_synthesis."""

    @pytest.mark.asyncio
    async def test_scored_conversations_have_score_and_passed(self) -> None:
        """After run_synthesis, conversations have score and passed fields set."""
        meta_responses = [
            _make_llm_response("Hello [END]", role=ModelRole.META),
        ]
        target_responses = [
            # No target call needed since persona ends immediately after user message
        ]

        # Actually, persona sends "Hello" (no [END] yet), target responds, then [END]
        meta_responses = [
            _make_llm_response("Hello", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response("Hi there!", role=ModelRole.TARGET),
        ]

        scorer_result = CaseResult(
            case_id="",
            score=-2,
            passed=False,
            reason="Failed: criterion not met",
        )

        ds = AsyncMock()
        ds.add_case.return_value = (TestCase(id="synth-1", tags=["synthetic"]), [])
        ds.list_cases.return_value = []

        engine, _, _, judge_scorer, _ = _make_engine(
            meta_responses, target_responses, scorer_result, dataset_service=ds
        )
        persona = _make_persona()
        config = SynthesisConfig(num_conversations=1, max_turns=10)

        result = await engine.run_synthesis(
            prompt_id="test-prompt",
            prompt_template="You are helpful.",
            personas=[persona],
            config=config,
            existing_cases=[],
            tools=None,
            mocks=None,
        )

        assert len(result.conversations) == 1
        conv = result.conversations[0]
        assert conv.score == -2
        assert conv.passed is False

    @pytest.mark.asyncio
    async def test_default_behavior_criteria_when_persona_has_none(self) -> None:
        """When persona has no behavior_criteria, a default is used."""
        meta_responses = [
            _make_llm_response("Hi", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response("Hello!", role=ModelRole.TARGET),
        ]

        scorer_result = CaseResult(case_id="", score=0, passed=True, reason="OK")

        ds = AsyncMock()
        ds.list_cases.return_value = []

        engine, _, _, judge_scorer, _ = _make_engine(
            meta_responses, target_responses, scorer_result, dataset_service=ds
        )
        persona = _make_persona(behavior_criteria=[])
        config = SynthesisConfig(num_conversations=1, max_turns=10)

        await engine.run_synthesis(
            prompt_id="test-prompt",
            prompt_template="You are helpful.",
            personas=[persona],
            config=config,
            existing_cases=[],
            tools=None,
            mocks=None,
        )

        # Scorer should still be called with some behavior criteria
        judge_scorer.score.assert_called_once()
        call_kwargs = judge_scorer.score.call_args
        expected_arg = call_kwargs.kwargs.get(
            "expected", call_kwargs[0][0] if call_kwargs[0] else {}
        )
        assert "behavior" in expected_arg
        assert len(expected_arg["behavior"]) > 0


# ===========================================================================
# TestPersistence
# ===========================================================================


class TestPersistence:
    """Tests for persisting failing conversations and discarding passing ones."""

    @pytest.mark.asyncio
    async def test_failing_conversations_persisted(self) -> None:
        """Conversations with score < 0 are persisted via DatasetService.add_case."""
        meta_responses = [
            _make_llm_response("Test input", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response("Bad response", role=ModelRole.TARGET),
        ]

        scorer_result = CaseResult(case_id="", score=-2, passed=False, reason="Failed")

        ds = AsyncMock()
        ds.add_case.return_value = (TestCase(id="synth-case-1", tags=["synthetic"]), [])
        ds.list_cases.return_value = []

        engine, _, _, _, _ = _make_engine(
            meta_responses, target_responses, scorer_result, dataset_service=ds
        )
        persona = _make_persona()
        config = SynthesisConfig(num_conversations=1, max_turns=10)

        result = await engine.run_synthesis(
            prompt_id="test-prompt",
            prompt_template="You are helpful.",
            personas=[persona],
            config=config,
            existing_cases=[],
            tools=None,
            mocks=None,
        )

        ds.add_case.assert_called_once()
        call_args = ds.add_case.call_args
        assert call_args[0][0] == "test-prompt"  # prompt_id
        persisted_case = call_args[0][1]
        assert isinstance(persisted_case, TestCase)
        assert "synthetic" in persisted_case.tags
        assert result.total_persisted == 1
        assert result.total_discarded == 0
        assert result.conversations[0].persisted_case_id == "synth-case-1"

    @pytest.mark.asyncio
    async def test_passing_conversations_not_persisted(self) -> None:
        """Conversations with score >= 0 are not persisted."""
        meta_responses = [
            _make_llm_response("Test input", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response("Good response", role=ModelRole.TARGET),
        ]

        scorer_result = CaseResult(case_id="", score=0, passed=True, reason="Passed")

        ds = AsyncMock()
        ds.list_cases.return_value = []

        engine, _, _, _, _ = _make_engine(
            meta_responses, target_responses, scorer_result, dataset_service=ds
        )
        persona = _make_persona()
        config = SynthesisConfig(num_conversations=1, max_turns=10)

        result = await engine.run_synthesis(
            prompt_id="test-prompt",
            prompt_template="You are helpful.",
            personas=[persona],
            config=config,
            existing_cases=[],
            tools=None,
            mocks=None,
        )

        ds.add_case.assert_not_called()
        assert result.total_persisted == 0
        assert result.total_discarded == 1
        assert result.conversations[0].persisted_case_id is None


# ===========================================================================
# TestModelSeparation
# ===========================================================================


class TestModelSeparation:
    """Tests for persona/target model role separation (SYNTH-06)."""

    @pytest.mark.asyncio
    async def test_persona_uses_meta_model(self) -> None:
        """Persona (meta_provider) is called with ModelRole.META."""
        meta_responses = [
            _make_llm_response("Hello [END]", role=ModelRole.META),
        ]
        engine, meta_provider, _, _, _ = _make_engine(meta_responses, [])
        persona = _make_persona()

        await engine.simulate_conversation(
            persona=persona,
            prompt_template="You are a helpful assistant.",
            variables={},
            tools=None,
            mocks=None,
        )

        meta_provider.chat_completion.assert_called_once()
        call_kwargs = meta_provider.chat_completion.call_args.kwargs
        assert call_kwargs["role"] == ModelRole.META
        assert call_kwargs["model"] == "meta-model"

    @pytest.mark.asyncio
    async def test_target_uses_target_model(self) -> None:
        """Target (target_provider) is called with ModelRole.TARGET."""
        meta_responses = [
            _make_llm_response("Hi", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response("Hello!", role=ModelRole.TARGET),
        ]
        engine, _, target_provider, _, _ = _make_engine(meta_responses, target_responses)
        persona = _make_persona()

        await engine.simulate_conversation(
            persona=persona,
            prompt_template="You are a helpful assistant.",
            variables={},
            tools=None,
            mocks=None,
        )

        target_provider.chat_completion.assert_called_once()
        call_kwargs = target_provider.chat_completion.call_args.kwargs
        assert call_kwargs["role"] == ModelRole.TARGET
        assert call_kwargs["model"] == "target-model"

    @pytest.mark.asyncio
    async def test_meta_and_target_are_separate_providers(self) -> None:
        """Meta and target providers are different objects (no self-play)."""
        meta_responses = [
            _make_llm_response("Hi", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response("Hello!", role=ModelRole.TARGET),
        ]
        engine, meta_provider, target_provider, _, _ = _make_engine(
            meta_responses, target_responses
        )
        persona = _make_persona()

        await engine.simulate_conversation(
            persona=persona,
            prompt_template="You are an assistant.",
            variables={},
            tools=None,
            mocks=None,
        )

        # Both called, but they are different mock objects
        assert meta_provider is not target_provider
        meta_provider.chat_completion.assert_called()
        target_provider.chat_completion.assert_called()


# ===========================================================================
# TestVariableSampling
# ===========================================================================


class TestVariableSampling:
    """Tests for variable sampling from existing test cases."""

    @pytest.mark.asyncio
    async def test_variables_sampled_from_existing_cases(self) -> None:
        """When no variables provided, they are sampled from existing test cases."""
        existing_cases = [
            TestCase(id="c1", variables={"name": "Alice", "location": "NYC"}),
            TestCase(id="c2", variables={"name": "Bob", "location": "LA"}),
        ]

        meta_responses = [
            _make_llm_response("Hi", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response("Hello!", role=ModelRole.TARGET),
        ]
        scorer_result = CaseResult(case_id="", score=0, passed=True, reason="OK")
        ds = AsyncMock()
        ds.list_cases.return_value = []

        engine, _, _, _, _ = _make_engine(
            meta_responses, target_responses, scorer_result, dataset_service=ds
        )
        persona = _make_persona()
        config = SynthesisConfig(num_conversations=1, max_turns=10)

        # Seed random for deterministic test
        random.seed(42)
        result = await engine.run_synthesis(
            prompt_id="test-prompt",
            prompt_template="Hello {{ name }} from {{ location }}.",
            personas=[persona],
            config=config,
            existing_cases=existing_cases,
            tools=None,
            mocks=None,
        )

        # Variables should be from one of the existing cases
        conv = result.conversations[0]
        assert conv.variables in [
            {"name": "Alice", "location": "NYC"},
            {"name": "Bob", "location": "LA"},
        ]

    @pytest.mark.asyncio
    async def test_empty_variables_when_no_existing_cases(self) -> None:
        """When no existing cases, empty dict is used for variables."""
        meta_responses = [
            _make_llm_response("Hi", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response("Hello!", role=ModelRole.TARGET),
        ]
        scorer_result = CaseResult(case_id="", score=0, passed=True, reason="OK")
        ds = AsyncMock()
        ds.list_cases.return_value = []

        engine, _, _, _, _ = _make_engine(
            meta_responses, target_responses, scorer_result, dataset_service=ds
        )
        persona = _make_persona()
        config = SynthesisConfig(num_conversations=1, max_turns=10)

        result = await engine.run_synthesis(
            prompt_id="test-prompt",
            prompt_template="You are helpful.",
            personas=[persona],
            config=config,
            existing_cases=[],
            tools=None,
            mocks=None,
        )

        assert result.conversations[0].variables == {}


# ===========================================================================
# TestProgressEvents
# ===========================================================================


class TestProgressEvents:
    """Tests for event callback emission during run_synthesis."""

    @pytest.mark.asyncio
    async def test_events_emitted_during_synthesis(self) -> None:
        """run_synthesis emits progress events via callback."""
        meta_responses = [
            _make_llm_response("Hi", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response("Hello!", role=ModelRole.TARGET),
        ]
        scorer_result = CaseResult(case_id="", score=0, passed=True, reason="OK")
        ds = AsyncMock()
        ds.list_cases.return_value = []

        event_callback = AsyncMock()
        engine, _, _, _, _ = _make_engine(
            meta_responses,
            target_responses,
            scorer_result,
            dataset_service=ds,
            event_callback=event_callback,
        )
        persona = _make_persona()
        config = SynthesisConfig(num_conversations=1, max_turns=10)

        await engine.run_synthesis(
            prompt_id="test-prompt",
            prompt_template="You are helpful.",
            personas=[persona],
            config=config,
            existing_cases=[],
            tools=None,
            mocks=None,
        )

        # Should have emitted at least: synthesis_started, conversation_started,
        # conversation_scored, synthesis_complete
        event_types = [call.args[0] for call in event_callback.call_args_list]
        assert "synthesis_started" in event_types
        assert "conversation_started" in event_types
        assert "conversation_scored" in event_types
        assert "synthesis_complete" in event_types


# ===========================================================================
# TestSynthesisResult
# ===========================================================================


class TestSynthesisResult:
    """Tests for SynthesisResult aggregation."""

    @pytest.mark.asyncio
    async def test_result_totals_correct(self) -> None:
        """SynthesisResult has correct total_conversations, total_persisted, total_discarded."""
        # 2 conversations: first fails, second passes
        meta_responses = [
            # Conv 1
            _make_llm_response("Hi", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
            # Conv 2
            _make_llm_response("Hey", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response("Hello!", role=ModelRole.TARGET),
            _make_llm_response("Hey there!", role=ModelRole.TARGET),
        ]

        # Return failing then passing score
        scorer_results = [
            CaseResult(case_id="", score=-2, passed=False, reason="Failed"),
            CaseResult(case_id="", score=0, passed=True, reason="OK"),
        ]

        ds = AsyncMock()
        ds.add_case.return_value = (TestCase(id="synth-1", tags=["synthetic"]), [])
        ds.list_cases.return_value = []

        meta_provider = AsyncMock()
        target_provider = AsyncMock()
        judge_scorer = AsyncMock()
        meta_provider.chat_completion.side_effect = meta_responses
        target_provider.chat_completion.side_effect = target_responses
        judge_scorer.score.side_effect = scorer_results

        engine = SynthesisEngine(
            meta_provider=meta_provider,
            target_provider=target_provider,
            judge_scorer=judge_scorer,
            dataset_service=ds,
            meta_model="meta-model",
            target_model="target-model",
        )

        persona = _make_persona()
        config = SynthesisConfig(num_conversations=2, max_turns=10)

        result = await engine.run_synthesis(
            prompt_id="test-prompt",
            prompt_template="You are helpful.",
            personas=[persona],
            config=config,
            existing_cases=[],
            tools=None,
            mocks=None,
        )

        assert result.total_conversations == 2
        assert result.total_persisted == 1
        assert result.total_discarded == 1

    @pytest.mark.asyncio
    async def test_persona_filtering_by_config(self) -> None:
        """Only personas matching config.persona_ids are used."""
        meta_responses = [
            _make_llm_response("Hi", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response("Hello!", role=ModelRole.TARGET),
        ]
        scorer_result = CaseResult(case_id="", score=0, passed=True, reason="OK")
        ds = AsyncMock()
        ds.list_cases.return_value = []

        engine, _, _, _, _ = _make_engine(
            meta_responses,
            target_responses,
            scorer_result,
            dataset_service=ds,
        )

        persona_a = _make_persona(id="persona-a")
        persona_b = _make_persona(id="persona-b")
        config = SynthesisConfig(
            num_conversations=1,
            max_turns=10,
            persona_ids=["persona-a"],  # Only run persona-a
        )

        result = await engine.run_synthesis(
            prompt_id="test-prompt",
            prompt_template="You are helpful.",
            personas=[persona_a, persona_b],
            config=config,
            existing_cases=[],
            tools=None,
            mocks=None,
        )

        assert result.total_conversations == 1
        assert result.conversations[0].persona_id == "persona-a"


# ===========================================================================
# TestPersonaSystemPromptLanguageChannel
# ===========================================================================


class TestPersonaSystemPromptLanguageChannel:
    """Tests for language and channel awareness in _build_persona_system_prompt.

    Covers LANG-03: Synthesis generates conversations in the persona's language natively.
    """

    def _build_prompt(self, **persona_overrides: Any) -> str:
        """Helper: build a persona system prompt using a minimally-mocked engine."""
        engine, _, _, _, _ = _make_engine()
        persona = _make_persona(**persona_overrides)
        return engine._build_persona_system_prompt(
            persona=persona,
            variables={"name": "Alice"},
            scenario_context=None,
        )

    def test_english_persona_no_language_directive(self) -> None:
        """English persona (language='en') system prompt does NOT include language directive."""
        prompt = self._build_prompt(language="en")
        assert "MUST speak in" not in prompt
        assert (
            "Language" not in prompt.split("## Your Persona")[0]
        )  # No language header before persona

    def test_spanish_persona_includes_language_directive(self) -> None:
        """Spanish persona (language='es') system prompt includes 'MUST speak in Spanish (es)'."""
        prompt = self._build_prompt(language="es")
        assert "MUST speak in Spanish (es)" in prompt

    def test_chinese_persona_includes_language_directive(self) -> None:
        """Chinese persona (language='zh') system prompt includes 'MUST speak in Chinese (zh)'."""
        prompt = self._build_prompt(language="zh")
        assert "MUST speak in Chinese (zh)" in prompt

    def test_voice_channel_includes_voice_conventions(self) -> None:
        """Voice channel (channel='voice') system prompt includes voice conventions."""
        prompt = self._build_prompt(channel="voice")
        assert "voice" in prompt.lower() or "Voice" in prompt
        assert "short sentences" in prompt.lower() or "Short sentences" in prompt
        assert "markdown" in prompt.lower()

    def test_text_channel_no_voice_conventions(self) -> None:
        """Text channel (channel='text') system prompt does NOT include voice convention section."""
        prompt = self._build_prompt(channel="text")
        assert "## Channel: Voice" not in prompt
        assert "phone call" not in prompt.lower()

    def test_combined_non_english_voice_includes_both(self) -> None:
        """Combined non-English + voice channel includes both language directive and voice conventions."""
        prompt = self._build_prompt(language="es", channel="voice")
        assert "MUST speak in Spanish (es)" in prompt
        assert "voice" in prompt.lower() or "Voice" in prompt

    def test_scenario_context_still_included(self) -> None:
        """Scenario context is still included when present (regression)."""
        engine, _, _, _, _ = _make_engine()
        persona = _make_persona()
        prompt = engine._build_persona_system_prompt(
            persona=persona,
            variables={},
            scenario_context="The customer is calling about a refund.",
        )
        assert "The customer is calling about a refund." in prompt

    def test_edge_cases_and_variables_still_rendered(self) -> None:
        """Edge cases and variables still rendered correctly (regression)."""
        prompt = self._build_prompt(edge_cases=["edge1", "edge2"])
        assert "edge1" in prompt
        assert "edge2" in prompt
        assert "name" in prompt  # Variable from the helper

    def test_unknown_language_code_falls_back(self) -> None:
        """Unknown language code uses the code itself as the language name."""
        prompt = self._build_prompt(language="xx")
        assert "MUST speak in xx (xx)" in prompt


# ===========================================================================
# TestLLMMockerCascade
# ===========================================================================


class TestLLMMockerCascade:
    """Tests for LLM mocker cascade: LLM mocker first, static MockMatcher fallback.

    Covers requirements:
    - MOCK-03: Scenario types passed to LLM mocker
    - MOCK-04: LLM mocker -> static MockMatcher fallback cascade
    """

    @pytest.mark.asyncio
    async def test_llm_mocker_response_used_when_available(self) -> None:
        """When llm_mocker returns a response, that response is used instead of MockMatcher."""
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
        }
        meta_responses = [
            _make_llm_response("What's the weather?", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response(content=None, tool_calls=[tool_call], role=ModelRole.TARGET),
            _make_llm_response("The weather in Paris is rainy.", role=ModelRole.TARGET),
        ]

        # Static mock would return "Static: Sunny"
        mocks = [
            MockDefinition(
                tool_name="get_weather",
                scenarios=[MockScenario(match_args={"city": "Paris"}, response="Static: Sunny")],
            )
        ]

        # LLM mocker returns a different response
        llm_mocker = AsyncMock()
        llm_mocker.generate_mock_response = AsyncMock(
            return_value='{"weather": "rainy", "temp": 15}'
        )

        format_guides = {"get_weather": ['{"weather": "sunny", "temp": 22}']}

        engine, _, _, _, _ = _make_engine(meta_responses, target_responses)
        engine._llm_mocker = llm_mocker
        engine._format_guides = format_guides

        record = await engine.simulate_conversation(
            persona=_make_persona(),
            prompt_template="You are a weather assistant.",
            variables={},
            tools=[{"type": "function", "function": {"name": "get_weather"}}],
            mocks=mocks,
            max_turns=5,
        )

        # The LLM mocker response should be used, not the static mock
        tool_msg = next(m for m in record.chat_history if m["role"] == "tool")
        assert '{"weather": "rainy", "temp": 15}' in tool_msg["content"]
        assert "Static: Sunny" not in tool_msg["content"]
        llm_mocker.generate_mock_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_static_when_llm_returns_none(self) -> None:
        """When llm_mocker returns None, MockMatcher is used as fallback."""
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city": "London"}'},
        }
        meta_responses = [
            _make_llm_response("What's the weather?", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response(content=None, tool_calls=[tool_call], role=ModelRole.TARGET),
            _make_llm_response("The weather in London is sunny.", role=ModelRole.TARGET),
        ]

        mocks = [
            MockDefinition(
                tool_name="get_weather",
                scenarios=[
                    MockScenario(match_args={"city": "London"}, response="Static: Sunny, 22C")
                ],
            )
        ]

        # LLM mocker returns None (failure)
        llm_mocker = AsyncMock()
        llm_mocker.generate_mock_response = AsyncMock(return_value=None)

        format_guides = {"get_weather": ['{"weather": "sunny", "temp": 22}']}

        engine, _, _, _, _ = _make_engine(meta_responses, target_responses)
        engine._llm_mocker = llm_mocker
        engine._format_guides = format_guides

        record = await engine.simulate_conversation(
            persona=_make_persona(),
            prompt_template="You are a weather assistant.",
            variables={},
            tools=[{"type": "function", "function": {"name": "get_weather"}}],
            mocks=mocks,
            max_turns=5,
        )

        # Static mock should be used as fallback
        tool_msg = next(m for m in record.chat_history if m["role"] == "tool")
        assert "Static: Sunny, 22C" in tool_msg["content"]
        llm_mocker.generate_mock_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_llm_mocker_uses_static_directly(self) -> None:
        """When llm_mocker is None (not provided), MockMatcher is used directly."""
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city": "Berlin"}'},
        }
        meta_responses = [
            _make_llm_response("What's the weather?", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response(content=None, tool_calls=[tool_call], role=ModelRole.TARGET),
            _make_llm_response("The weather in Berlin is cold.", role=ModelRole.TARGET),
        ]

        mocks = [
            MockDefinition(
                tool_name="get_weather",
                scenarios=[
                    MockScenario(match_args={"city": "Berlin"}, response="Static: Cold, 5C")
                ],
            )
        ]

        # No llm_mocker set -- default None behavior
        engine, _, _, _, _ = _make_engine(meta_responses, target_responses)

        record = await engine.simulate_conversation(
            persona=_make_persona(),
            prompt_template="You are a weather assistant.",
            variables={},
            tools=[{"type": "function", "function": {"name": "get_weather"}}],
            mocks=mocks,
            max_turns=5,
        )

        # Static mock should be used
        tool_msg = next(m for m in record.chat_history if m["role"] == "tool")
        assert "Static: Cold, 5C" in tool_msg["content"]

    @pytest.mark.asyncio
    async def test_scenario_type_passed_to_llm_mocker(self) -> None:
        """Scenario type is derived from scenario_context and passed to llm_mocker."""
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"id": "123"}'},
        }
        meta_responses = [
            _make_llm_response("Look it up", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response(content=None, tool_calls=[tool_call], role=ModelRole.TARGET),
            _make_llm_response("Found it.", role=ModelRole.TARGET),
        ]

        mocks = [
            MockDefinition(
                tool_name="lookup",
                scenarios=[MockScenario(match_args={}, response="static fallback")],
            )
        ]

        llm_mocker = AsyncMock()
        llm_mocker.generate_mock_response = AsyncMock(return_value='{"result": "found"}')

        format_guides = {"lookup": ['{"result": "example"}']}

        engine, _, _, _, _ = _make_engine(meta_responses, target_responses)
        engine._llm_mocker = llm_mocker
        engine._format_guides = format_guides

        # Use "failure" scenario_context so scenario_type should be "failure"
        await engine.simulate_conversation(
            persona=_make_persona(),
            prompt_template="You are an assistant.",
            variables={},
            tools=[{"type": "function", "function": {"name": "lookup"}}],
            mocks=mocks,
            max_turns=5,
            scenario_context="The user encounters a failure when looking up data.",
        )

        # Verify scenario_type was passed as "failure" to generate_mock_response
        call_kwargs = llm_mocker.generate_mock_response.call_args
        assert call_kwargs.kwargs.get("scenario_type") == "failure" or (
            len(call_kwargs.args) >= 4 and call_kwargs.args[3] == "failure"
        )

    @pytest.mark.asyncio
    async def test_no_format_guide_for_tool_skips_llm_mocker(self) -> None:
        """When format_guides has no entry for the tool, LLM mocker is skipped."""
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city": "Tokyo"}'},
        }
        meta_responses = [
            _make_llm_response("Check weather", role=ModelRole.META),
            _make_llm_response("[END]", role=ModelRole.META),
        ]
        target_responses = [
            _make_llm_response(content=None, tool_calls=[tool_call], role=ModelRole.TARGET),
            _make_llm_response("Weather in Tokyo.", role=ModelRole.TARGET),
        ]

        mocks = [
            MockDefinition(
                tool_name="get_weather",
                scenarios=[MockScenario(match_args={"city": "Tokyo"}, response="Static: Hot, 35C")],
            )
        ]

        llm_mocker = AsyncMock()
        llm_mocker.generate_mock_response = AsyncMock(return_value='{"temp": 35}')

        # Format guides exist but NOT for "get_weather"
        format_guides = {"other_tool": ['{"data": "example"}']}

        engine, _, _, _, _ = _make_engine(meta_responses, target_responses)
        engine._llm_mocker = llm_mocker
        engine._format_guides = format_guides

        record = await engine.simulate_conversation(
            persona=_make_persona(),
            prompt_template="You are a weather assistant.",
            variables={},
            tools=[{"type": "function", "function": {"name": "get_weather"}}],
            mocks=mocks,
            max_turns=5,
        )

        # LLM mocker should NOT be called (no format guide for this tool)
        llm_mocker.generate_mock_response.assert_not_called()
        # Static mock should be used
        tool_msg = next(m for m in record.chat_history if m["role"] == "tool")
        assert "Static: Hot, 35C" in tool_msg["content"]
