"""Tests for FitnessEvaluator pipeline orchestrator.

Tests the full evaluation pipeline: render -> infer -> score -> aggregate.
Uses mocked LLM client, scorers, and cost tracker to verify orchestration logic.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.config.models import GenerationConfig
from api.dataset.models import PriorityTier, TestCase
from api.evaluation.aggregator import FitnessAggregator
from api.evaluation.models import CaseResult, EvaluationReport, FitnessScore
from api.evaluation.renderer import TemplateRenderer, TemplateRenderError
from api.evaluation.scorers import BehaviorJudgeScorer, ExactMatchScorer
from api.exceptions import RetryableError
from api.gateway.cost import CostTracker
from api.gateway.litellm_provider import LiteLLMProvider
from api.types import LLMResponse, ModelRole

# -- Fixtures ------------------------------------------------------------------


def _make_llm_response(
    content: str = "Hello!",
    tool_calls: list[dict] | None = None,
) -> LLMResponse:
    """Create a minimal LLMResponse for testing."""
    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        model_used="openai/gpt-4o-mini",
        role=ModelRole.TARGET,
        input_tokens=10,
        output_tokens=20,
        cost_usd=0.001,
        timestamp=datetime.now(UTC),
    )


def _make_case_result(
    case_id: str = "case-1",
    tier: str = "normal",
    score: float = 0.8,
    passed: bool = True,
    criteria_results: list[dict] | None = None,
) -> CaseResult:
    """Create a CaseResult for testing."""
    return CaseResult(
        case_id=case_id,
        tier=tier,
        score=score,
        passed=passed,
        reason="test",
        criteria_results=criteria_results,
    )


def _make_test_case(
    case_id: str = "case-1",
    tier: PriorityTier = PriorityTier.NORMAL,
    variables: dict | None = None,
    chat_history: list[dict] | None = None,
    expected_output: dict | None = None,
    tools: list[dict] | None = None,
) -> TestCase:
    """Create a TestCase for testing."""
    return TestCase(
        id=case_id,
        tier=tier,
        variables=variables or {"name": "Alice"},
        chat_history=chat_history or [{"role": "user", "content": "Hi"}],
        expected_output=expected_output,
        tools=tools,
    )


@pytest.fixture
def mock_client():
    """Mock LiteLLMProvider with default response."""
    client = AsyncMock(spec=LiteLLMProvider)
    client.chat_completion.return_value = _make_llm_response()
    return client


@pytest.fixture
def mock_renderer():
    """Mock TemplateRenderer that returns a rendered string."""
    renderer = MagicMock(spec=TemplateRenderer)
    renderer.render.return_value = "Hello Alice!"
    return renderer


@pytest.fixture
def mock_exact_scorer():
    """Mock ExactMatchScorer."""
    scorer = AsyncMock(spec=ExactMatchScorer)
    scorer.score.return_value = _make_case_result(score=1.0, passed=True)
    return scorer


@pytest.fixture
def mock_behavior_scorer():
    """Mock BehaviorJudgeScorer."""
    scorer = AsyncMock(spec=BehaviorJudgeScorer)
    scorer.score.return_value = _make_case_result(score=0.8, passed=True, criteria_results=None)
    return scorer


@pytest.fixture
def mock_aggregator():
    """Mock FitnessAggregator."""
    aggregator = MagicMock(spec=FitnessAggregator)
    aggregator.aggregate.return_value = FitnessScore(score=0.85, rejected=False, case_results=[])
    return aggregator


@pytest.fixture
def mock_cost_tracker():
    """Mock CostTracker."""
    tracker = MagicMock(spec=CostTracker)
    tracker.summary.return_value = {
        "total_calls": 1,
        "total_input_tokens": 10,
        "total_output_tokens": 20,
        "total_cost_usd": 0.001,
    }
    return tracker


@pytest.fixture
def gen_config():
    """Default GenerationConfig."""
    return GenerationConfig(temperature=0.7, max_tokens=4096)


@pytest.fixture
def evaluator(
    mock_client,
    mock_renderer,
    mock_exact_scorer,
    mock_behavior_scorer,
    mock_aggregator,
    mock_cost_tracker,
):
    """FitnessEvaluator with the default test doubles."""
    from api.evaluation.evaluator import FitnessEvaluator

    return FitnessEvaluator(
        client=mock_client,
        renderer=mock_renderer,
        exact_scorer=mock_exact_scorer,
        behavior_scorer=mock_behavior_scorer,
        aggregator=mock_aggregator,
        cost_tracker=mock_cost_tracker,
        evaluation_concurrency=2,
    )


@pytest.fixture
def cases():
    """Stable cases for evaluation-cache tests."""
    return [
        _make_test_case(case_id="first", expected_output={"content": "Hello"}),
        _make_test_case(case_id="second", expected_output={"content": "World"}),
    ]


# -- Tests: Init ---------------------------------------------------------------


class TestFitnessEvaluatorInit:
    """Tests for FitnessEvaluator construction."""

    def test_init_stores_components(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
    ):
        """FitnessEvaluator stores all injected components."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )
        assert evaluator is not None

    def test_init_rejects_zero_evaluation_concurrency(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
    ):
        from api.evaluation.evaluator import FitnessEvaluator

        with pytest.raises(ValueError, match="evaluation_concurrency must be at least 1"):
            FitnessEvaluator(
                client=mock_client,
                renderer=mock_renderer,
                exact_scorer=mock_exact_scorer,
                behavior_scorer=mock_behavior_scorer,
                aggregator=mock_aggregator,
                cost_tracker=mock_cost_tracker,
                evaluation_concurrency=0,
            )


# -- Tests: Pipeline -----------------------------------------------------------


class TestFitnessEvaluatorPipeline:
    """Tests for the evaluate() pipeline."""

    @pytest.mark.asyncio
    async def test_evaluate_calls_renderer_with_correct_variables(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """evaluate() calls renderer.render with template and case variables."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(variables={"name": "Bob"})
        template = "Hello {{ name }}!"

        await evaluator.evaluate(
            template=template,
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        mock_renderer.render.assert_called_once_with(template, {"name": "Bob"})

    @pytest.mark.asyncio
    async def test_evaluate_calls_client_with_correct_messages(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """evaluate() builds messages [system + chat_history] and calls client."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(
            chat_history=[{"role": "user", "content": "Hi there"}],
        )

        await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        call_args = mock_client.chat_completion.call_args
        messages = call_args.kwargs.get("messages", call_args[0][0] if call_args[0] else None)
        assert messages[0] == {"role": "system", "content": "Hello Alice!"}
        assert messages[1] == {"role": "user", "content": "Hi there"}

    @pytest.mark.asyncio
    async def test_evaluate_routes_tool_calls_to_exact_scorer(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """evaluate() uses ExactMatchScorer when expected has only tool_calls."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(
            expected_output={"tool_calls": [{"name": "get_weather", "arguments": {}}]},
        )

        await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        mock_exact_scorer.score.assert_called_once()
        mock_behavior_scorer.score.assert_not_called()

    @pytest.mark.asyncio
    async def test_evaluate_routes_text_to_behavior_scorer(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """evaluate() uses BehaviorJudgeScorer when expected has no tool_calls."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(expected_output={"content": "Hello!"})

        await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        mock_behavior_scorer.score.assert_called_once()
        mock_exact_scorer.score.assert_not_called()

    @pytest.mark.asyncio
    async def test_evaluate_uses_behavior_scorer_when_no_expected_output(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """evaluate() routes to BehaviorJudgeScorer when expected_output is None."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(expected_output=None)

        await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        mock_behavior_scorer.score.assert_called_once()
        mock_exact_scorer.score.assert_not_called()

    @pytest.mark.asyncio
    async def test_evaluate_returns_evaluation_report(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """evaluate() returns an EvaluationReport with all fields populated."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(expected_output={"content": "Hello!"})

        report = await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        assert isinstance(report, EvaluationReport)
        assert report.total_cases == 1
        assert len(report.case_results) == 1
        assert report.fitness.score == 0.85
        assert report.cost_summary["total_calls"] == 1

    @pytest.mark.asyncio
    async def test_evaluate_handles_rendering_error_gracefully(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """evaluate() gives score=-2 (render penalty) when rendering fails."""
        from api.evaluation.evaluator import FitnessEvaluator

        mock_renderer.render.side_effect = TemplateRenderError("Missing variable: foo")

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case()

        report = await evaluator.evaluate(
            template="Hello {{ foo }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        # Should not call client or scorers when rendering fails
        mock_client.chat_completion.assert_not_called()
        mock_exact_scorer.score.assert_not_called()
        mock_behavior_scorer.score.assert_not_called()

        # Case result should have score=-2 (render penalty) with error reason
        assert len(report.case_results) == 1
        result = report.case_results[0]
        assert result.score == -2
        assert result.passed is False
        assert "Missing variable: foo" in result.reason

    @pytest.mark.asyncio
    async def test_evaluate_annotates_case_id_and_tier(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """evaluate() sets case_id and tier on each CaseResult."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(
            case_id="my-case-42",
            tier=PriorityTier.CRITICAL,
            expected_output={"content": "Hello!"},
        )

        report = await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        result = report.case_results[0]
        assert result.case_id == "my-case-42"
        assert result.tier == "critical"

    @pytest.mark.asyncio
    async def test_evaluate_passes_purpose_to_behavior_scorer_context(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """evaluate() passes purpose to BehaviorJudgeScorer context."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(expected_output={"content": "Hello!"})

        await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
            purpose="Test customer greeting quality",
        )

        call_args = mock_behavior_scorer.score.call_args
        context = call_args.kwargs.get("context", call_args[1] if len(call_args) > 1 else None)
        assert context["purpose"] == "Test customer greeting quality"

    @pytest.mark.asyncio
    async def test_plain_provider_preserves_direct_cost_tracking(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """A directly constructed evaluator records plain-provider responses."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        cases = [
            _make_test_case(case_id="c1", expected_output={"content": "Hi"}),
            _make_test_case(case_id="c2", expected_output={"content": "Hey"}),
        ]

        await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=cases,
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        assert mock_cost_tracker.record.call_count == 2

    @pytest.mark.asyncio
    async def test_evaluate_passes_prompt_tools_when_case_has_no_tools(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """evaluate() passes prompt_tools to chat_completion when case has no case-specific tools."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        prompt_tools = [{"type": "function", "function": {"name": "get_weather"}}]
        case = _make_test_case(
            tools=None,
            expected_output={"tool_calls": [{"name": "get_weather", "arguments": {}}]},
        )

        await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
            prompt_tools=prompt_tools,
        )

        call_args = mock_client.chat_completion.call_args
        assert call_args.kwargs.get("tools") == prompt_tools

    @pytest.mark.asyncio
    async def test_evaluate_prefers_case_tools_over_prompt_tools(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """evaluate() uses case.tools when present, ignoring prompt_tools."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case_tools = [{"type": "function", "function": {"name": "search"}}]
        prompt_tools = [{"type": "function", "function": {"name": "get_weather"}}]

        case = _make_test_case(
            tools=case_tools,
            expected_output={"tool_calls": [{"name": "search", "arguments": {}}]},
        )

        await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
            prompt_tools=prompt_tools,
        )

        call_args = mock_client.chat_completion.call_args
        assert call_args.kwargs.get("tools") == case_tools

    @pytest.mark.asyncio
    async def test_evaluate_multiple_cases(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """evaluate() processes all cases and aggregates results."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        cases = [
            _make_test_case(
                case_id="c1",
                expected_output={"tool_calls": [{"name": "fn", "arguments": {}}]},
            ),
            _make_test_case(case_id="c2", expected_output={"content": "Hello!"}),
            _make_test_case(case_id="c3", expected_output=None),
        ]

        report = await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=cases,
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        # 3 cases processed
        assert report.total_cases == 3
        assert len(report.case_results) == 3

        # c1 -> exact scorer, c2 + c3 -> behavior scorer
        assert mock_exact_scorer.score.call_count == 1
        assert mock_behavior_scorer.score.call_count == 2

        # Aggregator called with all 3 results
        mock_aggregator.aggregate.assert_called_once()
        agg_args = mock_aggregator.aggregate.call_args[0][0]
        assert len(agg_args) == 3


# -- Tests: Concurrency and cache ---------------------------------------------


class TestFitnessEvaluatorConcurrencyAndCache:
    """Cases overlap within a bound and immutable reports are cached by all inputs."""

    @pytest.mark.asyncio
    async def test_evaluate_runs_cases_concurrently_but_preserves_order(
        self, evaluator, monkeypatch
    ):
        active = 0
        peak = 0

        async def fake_case(**kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            case = kwargs["case"]
            await asyncio.sleep({"first": 0.02, "second": 0.01}.get(case.id, 0))
            active -= 1
            return CaseResult(case_id=case.id, score=-1, passed=False)

        monkeypatch.setattr(evaluator, "_evaluate_case", fake_case)
        report = await evaluator.evaluate(
            template="Prompt",
            cases=[TestCase(id="first"), TestCase(id="second"), TestCase(id="third")],
            target_model="model",
            generation_config=GenerationConfig(),
        )

        assert peak == 2
        assert [result.case_id for result in report.case_results] == [
            "first",
            "second",
            "third",
        ]

    @pytest.mark.asyncio
    async def test_identical_evaluation_is_cached_as_a_deep_copy(self, evaluator, cases):
        first = await evaluator.evaluate("Prompt", cases, "model", GenerationConfig())
        expected = first.model_copy(deep=True)
        calls = evaluator._client.chat_completion.call_count
        first.case_results[0].reason = "mutated by caller"

        second = await evaluator.evaluate("Prompt", cases, "model", GenerationConfig())

        assert second == expected
        assert second is not first
        assert second.case_results[0] is not first.case_results[0]
        assert evaluator._client.chat_completion.call_count == calls

    @pytest.mark.asyncio
    async def test_failed_evaluation_is_not_cached(self, evaluator, cases, monkeypatch):
        calls = 0

        async def fail_once(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("incomplete evaluation")
            case = kwargs["case"]
            return CaseResult(case_id=case.id, score=0, passed=True)

        monkeypatch.setattr(evaluator, "_evaluate_case", fail_once)
        with pytest.raises(RuntimeError, match="incomplete evaluation"):
            await evaluator.evaluate("Prompt", cases, "model", GenerationConfig())

        report = await evaluator.evaluate("Prompt", cases, "model", GenerationConfig())

        assert report.total_cases == len(cases)
        assert calls > 1

    @pytest.mark.asyncio
    async def test_transient_provider_error_is_retried_on_identical_evaluation(
        self, evaluator, cases
    ):
        evaluator._client.chat_completion.side_effect = [
            RetryableError(429, "try again"),
            _make_llm_response(),
        ]
        case = cases[0]

        first = await evaluator.evaluate("Prompt", [case], "model", GenerationConfig())
        second = await evaluator.evaluate("Prompt", [case], "model", GenerationConfig())

        assert first.case_results[0].reason.startswith("API error:")
        assert evaluator._client.chat_completion.call_count == 2
        assert not second.case_results[0].reason.startswith("API error:")

    @pytest.mark.asyncio
    async def test_render_error_is_not_cached(self, evaluator):
        evaluator._renderer.render.side_effect = [TemplateRenderError("missing"), "rendered"]
        case = _make_test_case(expected_output={"content": "Hello"})

        first = await evaluator.evaluate("Prompt", [case], "model", GenerationConfig())
        second = await evaluator.evaluate("Prompt", [case], "model", GenerationConfig())

        assert first.case_results[0].reason.startswith("Rendering error:")
        assert evaluator._renderer.render.call_count == 2
        assert not second.case_results[0].reason.startswith("Rendering error:")

    @pytest.mark.asyncio
    async def test_tool_loop_error_is_explicit_and_not_cached(self, evaluator):
        evaluator._mocks = []
        tool_response = _make_llm_response(
            tool_calls=[
                {
                    "id": "call-1",
                    "function": {"name": "lookup", "arguments": "{}"},
                }
            ]
        )
        evaluator._client.chat_completion.side_effect = [
            tool_response,
            RetryableError(503, "tool continuation failed"),
            _make_llm_response(),
        ]
        case = _make_test_case(expected_output={"content": "Hello"})

        first = await evaluator.evaluate("Prompt", [case], "model", GenerationConfig())
        second = await evaluator.evaluate("Prompt", [case], "model", GenerationConfig())

        assert first.case_results[0].reason.startswith("Tool loop API error:")
        assert evaluator._behavior_scorer.score.call_count == 1
        assert evaluator._client.chat_completion.call_count == 3
        assert not second.case_results[0].reason.startswith("Tool loop API error:")

    @pytest.mark.asyncio
    async def test_ordinary_scored_failure_is_cached(self, evaluator):
        evaluator._behavior_scorer.score.return_value = _make_case_result(
            score=-1, passed=False
        )
        case = _make_test_case(expected_output={"content": "Hello"})

        first = await evaluator.evaluate("Prompt", [case], "model", GenerationConfig())
        calls = evaluator._client.chat_completion.call_count
        second = await evaluator.evaluate("Prompt", [case], "model", GenerationConfig())

        assert first.case_results[0].passed is False
        assert second == first
        assert evaluator._client.chat_completion.call_count == calls

    def test_cache_key_contains_every_evaluation_and_inference_input(self, evaluator, cases):
        base = {
            "template": "Prompt",
            "cases": cases,
            "target_model": "model",
            "generation_config": GenerationConfig(),
            "prompt_tools": [{"type": "function", "function": {"name": "lookup"}}],
            "purpose": "purpose",
        }
        original = evaluator._evaluation_cache_key(**base)
        changed_cases = [case.model_copy(deep=True) for case in cases]
        changed_cases[0].description = "cache-relevant metadata"
        variants = [
            {**base, "template": "Other"},
            {**base, "cases": changed_cases},
            {**base, "cases": list(reversed(cases))},
            {**base, "target_model": "other-model"},
            {**base, "generation_config": GenerationConfig(temperature=0.1)},
            {**base, "prompt_tools": None},
            {**base, "purpose": "other-purpose"},
        ]

        assert all(evaluator._evaluation_cache_key(**variant) != original for variant in variants)

        evaluator._extra_inference_kwargs = {"seed": 7}
        assert evaluator._evaluation_cache_key(**base) != original


# -- Tests: Behavior Routing ---------------------------------------------------


class TestBehaviorRouting:
    """Tests for the 4-way routing logic: tool_calls, behavior, combined, backward compat."""

    @pytest.mark.asyncio
    async def test_behavior_only_routes_to_behavior_scorer(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """Case with only behavior routes to BehaviorJudgeScorer."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(
            expected_output={"behavior": ["greets warmly", "transfers correctly"]},
        )

        await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        mock_behavior_scorer.score.assert_called_once()
        mock_exact_scorer.score.assert_not_called()

    @pytest.mark.asyncio
    async def test_combined_exact_passes_then_behavior_runs(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """Combined (tool_calls + behavior): ExactMatch passes -> BehaviorJudge runs."""
        from api.evaluation.evaluator import FitnessEvaluator

        mock_exact_scorer.score.return_value = _make_case_result(score=1.0, passed=True)
        mock_behavior_scorer.score.return_value = _make_case_result(
            score=1.0,
            passed=True,
            criteria_results=[{"criterion": "greets", "passed": True, "reason": "good"}],
        )

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(
            expected_output={
                "tool_calls": [{"name": "transfer", "arguments": {}}],
                "behavior": ["greets warmly"],
            },
        )

        await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        mock_exact_scorer.score.assert_called_once()
        mock_behavior_scorer.score.assert_called_once()

    @pytest.mark.asyncio
    async def test_combined_exact_fails_short_circuits(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """Combined case: ExactMatch fails -> short-circuit, BehaviorJudge NOT called."""
        from api.evaluation.evaluator import FitnessEvaluator

        mock_exact_scorer.score.return_value = _make_case_result(score=0.0, passed=False)

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(
            expected_output={
                "tool_calls": [{"name": "transfer", "arguments": {}}],
                "behavior": ["greets warmly"],
            },
        )

        await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        mock_exact_scorer.score.assert_called_once()
        mock_behavior_scorer.score.assert_not_called()

    @pytest.mark.asyncio
    async def test_backward_compat_content_only_routes_to_behavior(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """Backward compat: content-only case routes to BehaviorJudgeScorer with migrated criterion."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(expected_output={"content": "Hello world!"})

        await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        mock_behavior_scorer.score.assert_called_once()
        # Check that the expected passed to scorer has a behavior key with migrated content
        call_kwargs = mock_behavior_scorer.score.call_args.kwargs
        expected_arg = call_kwargs["expected"]
        assert "behavior" in expected_arg
        assert any("Hello world!" in c for c in expected_arg["behavior"])

    @pytest.mark.asyncio
    async def test_backward_compat_none_expected_routes_to_behavior(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """Backward compat: None expected_output routes to BehaviorJudgeScorer with generic criterion."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(expected_output=None)

        await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        mock_behavior_scorer.score.assert_called_once()
        call_kwargs = mock_behavior_scorer.score.call_args.kwargs
        expected_arg = call_kwargs["expected"]
        assert "behavior" in expected_arg

    @pytest.mark.asyncio
    async def test_evaluator_passes_conversation_to_behavior_scorer(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """Evaluator passes full messages (system + chat_history) as conversation context."""
        from api.evaluation.evaluator import FitnessEvaluator

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(
            expected_output={"behavior": ["is helpful"]},
            chat_history=[{"role": "user", "content": "Help me please"}],
        )

        await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        call_kwargs = mock_behavior_scorer.score.call_args.kwargs
        context = call_kwargs.get("context")
        assert "conversation" in context
        # Should have system + user messages
        assert len(context["conversation"]) == 2
        assert context["conversation"][0]["role"] == "system"
        assert context["conversation"][1]["content"] == "Help me please"


# -- Tests: Combined Scoring ---------------------------------------------------


class TestCombinedScoring:
    """Tests for combined (tool_calls + behavior) scoring logic."""

    @pytest.mark.asyncio
    async def test_combined_score_uses_min(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """Combined scoring sums exact_score + behavior_score (AND gate)."""
        from api.evaluation.evaluator import FitnessEvaluator

        mock_exact_scorer.score.return_value = _make_case_result(score=1.0, passed=True)
        mock_behavior_scorer.score.return_value = _make_case_result(
            score=0.667,
            passed=False,
            criteria_results=[
                {"criterion": "greets", "passed": True, "reason": "ok"},
                {"criterion": "confirms", "passed": True, "reason": "ok"},
                {"criterion": "transfers", "passed": False, "reason": "wrong"},
            ],
        )

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(
            expected_output={
                "tool_calls": [{"name": "transfer", "arguments": {}}],
                "behavior": ["greets", "confirms", "transfers"],
            },
        )

        report = await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        result = report.case_results[0]
        # sum(1.0 + 0.667) = 1.667 (AND gate)
        assert result.score == pytest.approx(1.667, rel=1e-2)

    @pytest.mark.asyncio
    async def test_combined_result_has_criteria_results(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """Combined result includes criteria_results from behavior scorer."""
        from api.evaluation.evaluator import FitnessEvaluator

        criteria = [{"criterion": "is polite", "passed": True, "reason": "Polite tone"}]
        mock_exact_scorer.score.return_value = _make_case_result(score=1.0, passed=True)
        mock_behavior_scorer.score.return_value = _make_case_result(
            score=1.0,
            passed=True,
            criteria_results=criteria,
        )

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(
            expected_output={
                "tool_calls": [{"name": "fn", "arguments": {}}],
                "behavior": ["is polite"],
            },
        )

        report = await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        result = report.case_results[0]
        assert result.criteria_results is not None
        assert len(result.criteria_results) == 1
        assert result.criteria_results[0]["criterion"] == "is polite"

    @pytest.mark.asyncio
    async def test_combined_reason_includes_both(
        self,
        mock_client,
        mock_renderer,
        mock_exact_scorer,
        mock_behavior_scorer,
        mock_aggregator,
        mock_cost_tracker,
        gen_config,
    ):
        """Combined result reason includes both ExactMatch and Behavior reasons."""
        from api.evaluation.evaluator import FitnessEvaluator

        mock_exact_scorer.score.return_value = CaseResult(
            case_id="c1",
            score=1.0,
            passed=True,
            reason="Full match",
        )
        mock_behavior_scorer.score.return_value = CaseResult(
            case_id="c1",
            score=1.0,
            passed=True,
            reason="[PASS] is polite: yes",
            criteria_results=[{"criterion": "is polite", "passed": True, "reason": "yes"}],
        )

        evaluator = FitnessEvaluator(
            client=mock_client,
            renderer=mock_renderer,
            exact_scorer=mock_exact_scorer,
            behavior_scorer=mock_behavior_scorer,
            aggregator=mock_aggregator,
            cost_tracker=mock_cost_tracker,
        )

        case = _make_test_case(
            expected_output={
                "tool_calls": [{"name": "fn", "arguments": {}}],
                "behavior": ["is polite"],
            },
        )

        report = await evaluator.evaluate(
            template="Hello {{ name }}!",
            cases=[case],
            target_model="openai/gpt-4o-mini",
            generation_config=gen_config,
        )

        result = report.case_results[0]
        assert "ExactMatch" in result.reason
        assert "Behavior" in result.reason


@pytest.mark.asyncio
async def test_plain_provider_records_initial_and_tool_loop_responses(evaluator, monkeypatch):
    async def resolve(*_args, **_kwargs):
        return "tool result"

    monkeypatch.setattr("api.evaluation.evaluator.resolve_tool_call", resolve)
    evaluator._mocks = []
    evaluator._client.chat_completion.side_effect = [
        _make_llm_response(
            tool_calls=[
                {"id": "call-1", "function": {"name": "lookup", "arguments": "{}"}}
            ]
        ),
        _make_llm_response(),
    ]
    case = _make_test_case(expected_output={"content": "Hello"})

    await evaluator.evaluate("Prompt", [case], "model", GenerationConfig())

    assert evaluator._cost_tracker.record.call_count == 2
