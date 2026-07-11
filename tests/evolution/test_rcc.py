"""Tests for the RCC (Refinement through Critical Conversation) engine.

Tests use AsyncMock for the LiteLLMProvider and real instances of
TemplateValidator and CostTracker (both are pure logic, no I/O).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from api.evaluation.models import (
    CaseResult,
    EvaluationReport,
    FitnessScore,
)
from api.evaluation.validator import TemplateValidator
from api.evolution.models import Candidate
from api.evolution.rcc import RCCEngine
from api.gateway.cost import CostTracker
from api.gateway.litellm_provider import LiteLLMProvider
from api.types import LLMResponse, ModelRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_response(content: str) -> LLMResponse:
    """Build a minimal LLMResponse for mocking."""
    return LLMResponse(
        content=content,
        model_used="test-meta-model",
        role=ModelRole.META,
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.001,
        timestamp=datetime.now(UTC),
    )


def _make_parent(
    template: str = "Hello {{ name }}, your role is {{ role }}.",
    fitness: float = 0.7,
    case_results: list[CaseResult] | None = None,
) -> Candidate:
    """Build a parent Candidate with optional evaluation."""
    if case_results is None:
        case_results = [
            CaseResult(case_id="c1", score=1.0, passed=True, reason="ok"),
            CaseResult(
                case_id="c2",
                tier="critical",
                score=0.0,
                passed=False,
                reason="Wrong greeting format",
            ),
        ]
    report = EvaluationReport(
        fitness=FitnessScore(score=fitness),
        case_results=case_results,
        total_cases=len(case_results),
    )
    return Candidate(
        template=template,
        fitness_score=fitness,
        evaluation=report,
    )


def _build_engine(
    mock_client: AsyncMock,
    cost_tracker: CostTracker | None = None,
    max_retries: int = 3,
) -> RCCEngine:
    """Build an RCCEngine with the given mock client."""
    return RCCEngine(
        client=mock_client,
        cost_tracker=cost_tracker or CostTracker(),
        validator=TemplateValidator(),
        meta_model="test-meta-model",
        max_retries=max_retries,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSingleTurnRCC:
    """rcc_rounds=1: critic called once, author called once."""

    @pytest.mark.asyncio
    async def test_single_turn_rcc(self):
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            _make_llm_response("The greeting is too generic."),
            _make_llm_response(
                "<revised_template>Welcome {{ name }}, your role is {{ role }}!</revised_template>"
            ),
        ]

        engine = _build_engine(mock_client)
        parent = _make_parent()

        drafts = await engine.run_conversation(
            parents=[parent],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        assert drafts[0].template == "Welcome {{ name }}, your role is {{ role }}!"
        assert len(drafts) == 1
        assert mock_client.chat_completion.call_count == 2


class TestMultiTurnRCC:
    """rcc_rounds=3: critic/author called 3 times each."""

    @pytest.mark.asyncio
    async def test_multi_turn_rcc(self):
        mock_client = AsyncMock(spec=LiteLLMProvider)
        # 3 turns x 2 calls each = 6 total calls
        mock_client.chat_completion.side_effect = [
            # Turn 1
            _make_llm_response("Critique turn 1"),
            _make_llm_response("<revised_template>Rev1 {{ name }} {{ role }}</revised_template>"),
            # Turn 2
            _make_llm_response("Critique turn 2"),
            _make_llm_response("<revised_template>Rev2 {{ name }} {{ role }}</revised_template>"),
            # Turn 3
            _make_llm_response("Critique turn 3"),
            _make_llm_response("<revised_template>Rev3 {{ name }} {{ role }}</revised_template>"),
        ]

        engine = _build_engine(mock_client)
        parent = _make_parent()

        drafts = await engine.run_conversation(
            parents=[parent],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=3,
            generation=2,
        )

        # Final template is from last turn
        assert [draft.template for draft in drafts] == ["Rev3 {{ name }} {{ role }}"]
        assert mock_client.chat_completion.call_count == 6
        second_critic = mock_client.chat_completion.call_args_list[2].kwargs["messages"][1][
            "content"
        ]
        assert "Rev1 {{ name }} {{ role }}" in second_critic


@pytest.mark.asyncio
async def test_critic_receives_every_parent_template_and_failure():
    client = AsyncMock(spec=LiteLLMProvider)
    client.chat_completion.side_effect = [
        _make_llm_response("Combine both strengths"),
        _make_llm_response("<revised_template>{{ name }} {{ role }}</revised_template>"),
    ]
    first = _make_parent(
        template="FIRST {{ name }} {{ role }}",
        case_results=[
            CaseResult(case_id="first-failure", score=0.0, passed=False, reason="First failed")
        ],
    )
    second = _make_parent(
        template="SECOND {{ name }} {{ role }}",
        case_results=[
            CaseResult(case_id="second-failure", score=0.0, passed=False, reason="Second failed")
        ],
    )

    drafts = await _build_engine(client).run_conversation(
        parents=[first, second],
        original_template="Seed {{ name }} {{ role }}",
        anchor_variables={"name", "role"},
        purpose="greeting",
        rcc_rounds=1,
        generation=1,
    )

    critic_text = client.chat_completion.call_args_list[0].kwargs["messages"][1]["content"]
    assert "FIRST" in critic_text
    assert "SECOND" in critic_text
    assert "First failed" in critic_text
    assert "Second failed" in critic_text
    assert drafts[0].parent_ids == [first.id, second.id]


@pytest.mark.asyncio
async def test_paper_reference_evaluates_and_returns_each_round():
    client = AsyncMock(spec=LiteLLMProvider)
    client.chat_completion.side_effect = [
        _make_llm_response("critique one"),
        _make_llm_response("<revised_template>One {{ name }} {{ role }}</revised_template>"),
        _make_llm_response("critique two"),
        _make_llm_response("<revised_template>Two {{ name }} {{ role }}</revised_template>"),
        _make_llm_response("critique three"),
        _make_llm_response("<revised_template>Three {{ name }} {{ role }}</revised_template>"),
        _make_llm_response("critique four"),
        _make_llm_response("<revised_template>Four {{ name }} {{ role }}</revised_template>"),
    ]
    evaluated: list[str] = []

    async def evaluate(candidate: Candidate) -> Candidate:
        evaluated.append(candidate.template)
        round_number = len(evaluated)
        candidate.evaluation = _make_parent(
            case_results=[
                CaseResult(
                    case_id=f"round-{round_number}",
                    score=0.0,
                    passed=False,
                    reason=f"evidence from round {round_number}",
                )
            ]
        ).evaluation
        return candidate

    drafts = await _build_engine(client).run_conversation(
        parents=[_make_parent()],
        original_template="Seed {{ name }} {{ role }}",
        anchor_variables={"name", "role"},
        purpose="greeting",
        rcc_rounds=4,
        generation=1,
        evaluate_draft=evaluate,
    )

    assert evaluated == [
        "One {{ name }} {{ role }}",
        "Two {{ name }} {{ role }}",
        "Three {{ name }} {{ role }}",
        "Four {{ name }} {{ role }}",
    ]
    assert [draft.template for draft in drafts] == evaluated
    assert len(drafts) == 4
    assert client.chat_completion.call_count == 8
    for round_number, critic_call_index in [(1, 2), (2, 4), (3, 6)]:
        critic_text = client.chat_completion.call_args_list[critic_call_index].kwargs["messages"][
            1
        ]["content"]
        assert f"evidence from round {round_number}" in critic_text


class TestNoParentFreshGeneration:
    """Empty parents list triggers fresh generation."""

    @pytest.mark.asyncio
    async def test_no_parent_fresh_generation(self):
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            _make_llm_response(
                "<revised_template>Fresh {{ name }} prompt for {{ role }}</revised_template>"
            ),
            _make_llm_response("Improve the fresh draft."),
            _make_llm_response(
                "<revised_template>Refined {{ name }} prompt for {{ role }}</revised_template>"
            ),
        ]

        engine = _build_engine(mock_client)

        drafts = await engine.run_conversation(
            parents=[],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=2,
            generation=1,
        )

        # The fresh call is round one; the remaining round is critic + author.
        assert mock_client.chat_completion.call_count == 3
        assert [draft.template for draft in drafts] == [
            "Refined {{ name }} prompt for {{ role }}"
        ]
        assert drafts[0].parent_ids == []
        assert drafts[0].generation == 1

    @pytest.mark.asyncio
    async def test_fresh_generation_retries_invalid_first_round(self):
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            _make_llm_response("<revised_template>Missing role {{ name }}</revised_template>"),
            _make_llm_response(
                "<revised_template>Fresh {{ name }} prompt for {{ role }}</revised_template>"
            ),
        ]

        drafts = await _build_engine(mock_client).run_conversation(
            parents=[],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        assert mock_client.chat_completion.call_count == 2
        assert drafts[0].template == "Fresh {{ name }} prompt for {{ role }}"

    @pytest.mark.asyncio
    async def test_fresh_generation_retries_unchanged_original(self):
        original = "Hello {{ name }}, your role is {{ role }}."
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            _make_llm_response(f"<revised_template>{original}</revised_template>"),
            _make_llm_response(
                "<revised_template>Fresh {{ name }} prompt for {{ role }}</revised_template>"
            ),
        ]

        drafts = await _build_engine(mock_client).run_conversation(
            parents=[],
            original_template=original,
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        assert mock_client.chat_completion.call_count == 2
        assert [draft.template for draft in drafts] == [
            "Fresh {{ name }} prompt for {{ role }}"
        ]

    @pytest.mark.asyncio
    async def test_fresh_generation_retries_empty_output(self):
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            _make_llm_response("<revised_template></revised_template>"),
            _make_llm_response(
                "<revised_template>Fresh {{ name }} prompt for {{ role }}</revised_template>"
            ),
        ]

        drafts = await _build_engine(mock_client).run_conversation(
            parents=[],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        assert mock_client.chat_completion.call_count == 2
        assert [draft.template for draft in drafts] == [
            "Fresh {{ name }} prompt for {{ role }}"
        ]

    @pytest.mark.asyncio
    async def test_fresh_malformed_jinja_retries_and_never_escapes(self):
        mock_client = AsyncMock(spec=LiteLLMProvider)
        malformed = "<revised_template>Hello {{ name }, role {{ role }}</revised_template>"
        mock_client.chat_completion.side_effect = [
            _make_llm_response(malformed),
            _make_llm_response(malformed),
        ]

        drafts = await _build_engine(mock_client, max_retries=2).run_conversation(
            parents=[],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        assert drafts == []
        assert mock_client.chat_completion.call_count == 2


class TestVariablePreservationRetry:
    """Author drops a variable; retry succeeds on second attempt."""

    @pytest.mark.asyncio
    async def test_variable_preservation_retry(self):
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            # Critic
            _make_llm_response("The prompt needs improvement."),
            # Author attempt 1: drops {{ role }}
            _make_llm_response("<revised_template>Hello {{ name }}!</revised_template>"),
            # Author attempt 2 (retry): includes both variables
            _make_llm_response(
                "<revised_template>Hello {{ name }}, assigned {{ role }}.</revised_template>"
            ),
        ]

        engine = _build_engine(mock_client, max_retries=3)
        parent = _make_parent()

        drafts = await engine.run_conversation(
            parents=[parent],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        # 1 critic + 2 author attempts = 3 calls
        assert mock_client.chat_completion.call_count == 3
        assert drafts[0].template == "Hello {{ name }}, assigned {{ role }}."

    @pytest.mark.asyncio
    async def test_malformed_jinja_retries_inside_author_loop(self):
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            _make_llm_response("The prompt needs improvement."),
            _make_llm_response(
                "<revised_template>Hello {{ name }, role {{ role }}</revised_template>"
            ),
            _make_llm_response(
                "<revised_template>Hello {{ name }}, role {{ role }}</revised_template>"
            ),
        ]

        drafts = await _build_engine(mock_client).run_conversation(
            parents=[_make_parent()],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        assert mock_client.chat_completion.call_count == 3
        assert drafts[0].template == "Hello {{ name }}, role {{ role }}"


class TestAllRetriesFailRejectsConversation:
    """All retries produce invalid templates; no fallback escapes as a draft."""

    @pytest.mark.asyncio
    async def test_all_retries_fail_returns_no_draft(self):
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            # Critic
            _make_llm_response("Issues found."),
            # All 3 author attempts drop {{ role }}
            _make_llm_response("<revised_template>Fail1 {{ name }}</revised_template>"),
            _make_llm_response("<revised_template>Fail2 {{ name }}</revised_template>"),
            _make_llm_response("<revised_template>Fail3 {{ name }}</revised_template>"),
        ]

        engine = _build_engine(mock_client, max_retries=3)
        parent = _make_parent(template="Hello {{ name }}, your role is {{ role }}.")

        drafts = await engine.run_conversation(
            parents=[parent],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        assert drafts == []
        # 1 critic + 3 failed author attempts = 4 calls
        assert mock_client.chat_completion.call_count == 4

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "author_output",
        [
            "<revised_template></revised_template>",
            "<revised_template>Hello {{ name }}, your role is {{ role }}.</revised_template>",
        ],
        ids=["empty", "unchanged"],
    )
    async def test_empty_or_unchanged_output_is_not_returned(self, author_output: str):
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            _make_llm_response("Issues found."),
            _make_llm_response(author_output),
            _make_llm_response(author_output),
        ]

        drafts = await _build_engine(mock_client, max_retries=2).run_conversation(
            parents=[_make_parent()],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        assert drafts == []
        assert mock_client.chat_completion.call_count == 3


class TestTemplateExtraction:
    """Template extraction from LLM response content."""

    @pytest.mark.asyncio
    async def test_template_extraction_with_delimiters(self):
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            _make_llm_response("Critique here."),
            _make_llm_response(
                "Sure, here is the revised template:\n\n"
                "<revised_template>\nHello {{ name }}, welcome as {{ role }}!\n</revised_template>\n\n"
                "I made the greeting more welcoming."
            ),
        ]

        engine = _build_engine(mock_client)
        parent = _make_parent()

        drafts = await engine.run_conversation(
            parents=[parent],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        assert drafts[0].template == "Hello {{ name }}, welcome as {{ role }}!"

    @pytest.mark.asyncio
    async def test_template_extraction_without_delimiters(self):
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            _make_llm_response("Critique here."),
            _make_llm_response("Hello {{ name }}, welcome as {{ role }}!"),
        ]

        engine = _build_engine(mock_client)
        parent = _make_parent()

        drafts = await engine.run_conversation(
            parents=[parent],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        # Uses full content when no delimiters
        assert drafts[0].template == "Hello {{ name }}, welcome as {{ role }}!"


class TestCandidateLineage:
    """Candidate tracks parent_ids and generation number."""

    @pytest.mark.asyncio
    async def test_candidate_tracks_lineage(self):
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            _make_llm_response("Critique."),
            _make_llm_response("<revised_template>{{ name }} {{ role }}</revised_template>"),
        ]

        engine = _build_engine(mock_client)
        parent1 = _make_parent(fitness=0.8)
        parent2 = _make_parent(fitness=0.6)

        drafts = await engine.run_conversation(
            parents=[parent1, parent2],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=5,
        )

        assert drafts[0].generation == 5
        assert drafts[0].parent_ids == [parent1.id, parent2.id]


class TestCostTrackingOwnership:
    """The provider wrapper owns meta-model call accounting."""

    @pytest.mark.asyncio
    async def test_plain_provider_preserves_direct_cost_tracking(self):
        mock_client = AsyncMock(spec=LiteLLMProvider)
        # rcc_rounds=2: 2 critic + 2 author = 4 calls
        mock_client.chat_completion.side_effect = [
            _make_llm_response("Critique 1"),
            _make_llm_response("<revised_template>T1 {{ name }} {{ role }}</revised_template>"),
            _make_llm_response("Critique 2"),
            _make_llm_response("<revised_template>T2 {{ name }} {{ role }}</revised_template>"),
        ]

        cost_tracker = CostTracker()
        engine = _build_engine(mock_client, cost_tracker=cost_tracker)
        parent = _make_parent()

        await engine.run_conversation(
            parents=[parent],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=2,
            generation=1,
        )

        summary = cost_tracker.summary()
        assert mock_client.chat_completion.await_count == 4
        assert summary["total_calls"] == 4
        assert summary["total_cost_usd"] == pytest.approx(0.004)


class TestFailingCaseFormatting:
    """Failing cases are formatted with case_id, tier, score, reason."""

    def test_format_failing_cases(self):
        case_results = [
            CaseResult(
                case_id="c1",
                tier="critical",
                score=0.0,
                passed=False,
                reason="Wrong output format",
            ),
            CaseResult(case_id="c2", score=1.0, passed=True, reason="ok"),
            CaseResult(
                case_id="c3",
                tier="normal",
                score=0.3,
                passed=False,
                reason="Missing details",
            ),
        ]

        result = RCCEngine._format_failing_cases(case_results)
        assert "c1" in result
        assert "critical" in result
        assert "Wrong output format" in result
        assert "c3" in result
        assert "Missing details" in result
        # c2 should NOT be in failing cases (it passed)
        assert "c2" not in result

    def test_format_failing_cases_none_failing(self):
        case_results = [
            CaseResult(case_id="c1", score=1.0, passed=True, reason="ok"),
        ]
        result = RCCEngine._format_failing_cases(case_results)
        assert "No failing cases" in result


class TestPassingCasesSummary:
    """Passing cases are summarized (not full detail) for context."""

    def test_format_passing_summary(self):
        case_results = [
            CaseResult(case_id="c1", score=1.0, passed=True, reason="ok"),
            CaseResult(case_id="c2", score=0.0, passed=False, reason="fail"),
            CaseResult(case_id="c3", score=1.0, passed=True, reason="good"),
        ]

        result = RCCEngine._format_passing_summary(case_results)
        assert "2 case(s) passed" in result
        assert "c1" in result
        assert "c3" in result

    def test_format_passing_summary_none_passing(self):
        case_results = [
            CaseResult(case_id="c1", score=0.0, passed=False, reason="fail"),
        ]
        result = RCCEngine._format_passing_summary(case_results)
        assert "No passing cases" in result


class TestRetryMessageDistinguishesRenames:
    """Retry messages should distinguish renamed vars from dropped vars."""

    @pytest.mark.asyncio
    async def test_retry_mentions_rename_when_variable_renamed(self):
        """When author renames a variable, retry message should mention the rename."""
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            # Critic
            _make_llm_response("The prompt needs improvement."),
            # Author attempt 1: renames role_name -> role_title (string-similar)
            _make_llm_response(
                "<revised_template>Hello {{ name }}, your title is {{ role_title }}.</revised_template>"
            ),
            # Author attempt 2 (retry): correct
            _make_llm_response(
                "<revised_template>Hello {{ name }}, your assigned role is {{ role_name }}.</revised_template>"
            ),
        ]

        engine = _build_engine(mock_client, max_retries=3)
        parent = _make_parent(
            template="Hello {{ name }}, your role is {{ role_name }}.",
        )

        await engine.run_conversation(
            parents=[parent],
            original_template="Hello {{ name }}, your role is {{ role_name }}.",
            anchor_variables={"name", "role_name"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        # The retry call (3rd call = index 2) should mention "renamed" or "RENAMED"
        retry_call_args = mock_client.chat_completion.call_args_list[2]
        messages = retry_call_args.kwargs.get("messages") or retry_call_args[0][0]
        user_content = messages[1]["content"]
        # Should mention the rename, not just "dropped"
        assert "role_name" in user_content
        assert "role_title" in user_content
        # Should contain rename-related language
        assert "renamed" in user_content.lower() or "RENAMED" in user_content

    @pytest.mark.asyncio
    async def test_retry_says_dropped_when_variable_simply_removed(self):
        """When author just drops a variable with no rename, message says dropped."""
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            _make_llm_response("Critique."),
            # Author drops role entirely (no similar new var)
            _make_llm_response("<revised_template>Hello {{ name }}!</revised_template>"),
            # Retry: correct
            _make_llm_response(
                "<revised_template>Hello {{ name }}, role: {{ role }}.</revised_template>"
            ),
        ]

        engine = _build_engine(mock_client, max_retries=3)
        parent = _make_parent()

        await engine.run_conversation(
            parents=[parent],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        retry_call_args = mock_client.chat_completion.call_args_list[2]
        messages = retry_call_args.kwargs.get("messages") or retry_call_args[0][0]
        user_content = messages[1]["content"]
        assert "dropped" in user_content.lower()
        assert "role" in user_content


class TestCriticPromptIncludesVariables:
    """Critic prompt must include explicit variable names to prevent Gemini renames."""

    @pytest.mark.asyncio
    async def test_critic_system_prompt_contains_variable_names(self):
        """CRITIC_SYSTEM_PROMPT sent to LLM must list the anchor variable names."""
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            _make_llm_response("Critique."),
            _make_llm_response("<revised_template>{{ name }} {{ role }}</revised_template>"),
        ]
        engine = _build_engine(mock_client)
        parent = _make_parent()

        await engine.run_conversation(
            parents=[parent],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        # First call is critic; check system message content
        critic_call_args = mock_client.chat_completion.call_args_list[0]
        messages = critic_call_args.kwargs.get("messages") or critic_call_args[0][0]
        system_content = messages[0]["content"]
        assert "name" in system_content
        assert "role" in system_content

    @pytest.mark.asyncio
    async def test_critic_user_prompt_contains_variable_names(self):
        """CRITIC_USER_PROMPT sent to LLM must list the anchor variable names."""
        mock_client = AsyncMock(spec=LiteLLMProvider)
        mock_client.chat_completion.side_effect = [
            _make_llm_response("Critique."),
            _make_llm_response("<revised_template>{{ name }} {{ role }}</revised_template>"),
        ]
        engine = _build_engine(mock_client)
        parent = _make_parent()

        await engine.run_conversation(
            parents=[parent],
            original_template="Hello {{ name }}, your role is {{ role }}.",
            anchor_variables={"name", "role"},
            purpose="Generate greetings",
            rcc_rounds=1,
            generation=1,
        )

        critic_call_args = mock_client.chat_completion.call_args_list[0]
        messages = critic_call_args.kwargs.get("messages") or critic_call_args[0][0]
        user_content = messages[1]["content"]
        assert "name" in user_content
        assert "role" in user_content


class TestDiverseSelection:
    @pytest.mark.asyncio
    async def test_select_diverse_returns_meta_model_candidate_ids(self):
        client = AsyncMock(spec=LiteLLMProvider)
        candidates = [
            Candidate(id="first", template="First {{ name }}", fitness_score=0.9),
            Candidate(id="second", template="Second {{ name }}", fitness_score=0.8),
            Candidate(id="third", template="Third {{ name }}", fitness_score=0.7),
        ]
        client.chat_completion.return_value = _make_llm_response(
            "<candidate_ids>third, first</candidate_ids>"
        )

        selected = await _build_engine(client).select_diverse(candidates, 2)

        assert selected == [candidates[2], candidates[0]]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "response_content",
        [
            "<candidate_ids>feasible-high, feasible-low, rejected-high</candidate_ids>",
            "<candidate_ids>feasible-high, unknown</candidate_ids>",
            "<candidate_ids>feasible-high, feasible-low, feasible-low</candidate_ids>",
        ],
        ids=["overlong", "unknown", "trailing-duplicate"],
    )
    async def test_select_diverse_invalid_entire_list_uses_feasible_score_order(
        self,
        response_content: str,
    ):
        client = AsyncMock(spec=LiteLLMProvider)
        candidates = [
            Candidate(
                id="rejected-high",
                template="Rejected {{ name }}",
                fitness_score=0.95,
                rejected=True,
            ),
            Candidate(id="feasible-low", template="Low {{ name }}", fitness_score=0.6),
            Candidate(id="feasible-high", template="High {{ name }}", fitness_score=0.8),
        ]
        client.chat_completion.return_value = _make_llm_response(response_content)

        selected = await _build_engine(client).select_diverse(candidates, 2)

        assert selected == [candidates[2], candidates[1]]
