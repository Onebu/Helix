"""Deterministic pipeline regression tests.

Verifies that a mocked evolution run with fixed seed produces deterministic
fitness scores and selects the same best candidate across repeated runs.
Tests all pipeline components wiring: evaluator, RCC, selector, cost tracker.
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from api.config.models import GenerationConfig
from api.dataset.models import TestCase
from api.evaluation.aggregator import FitnessAggregator
from api.evaluation.evaluator import FitnessEvaluator
from api.evaluation.renderer import TemplateRenderer
from api.evaluation.scorers import BehaviorJudgeScorer, ExactMatchScorer
from api.evaluation.validator import TemplateValidator
from api.evolution.islands import IslandEvolver
from api.evolution.models import EvolutionConfig
from api.evolution.mutator import StructuralMutator
from api.evolution.rcc import RCCEngine
from api.evolution.selector import BoltzmannSelector
from api.gateway.cost import CostTracker
from api.gateway.protocol import LLMProvider
from api.types import LLMResponse, ModelRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIMPLE_TEMPLATE = "You are a helpful assistant. {{ instruction }}"


def _make_llm_response(
    content: str | None = None,
    tool_calls: list[dict] | None = None,
    role: ModelRole = ModelRole.TARGET,
) -> LLMResponse:
    """Create a minimal LLMResponse for mocking."""
    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        model_used="mock-model",
        role=role,
        input_tokens=10,
        output_tokens=20,
        cost_usd=0.001,
        timestamp=datetime.now(UTC),
    )


def _build_deterministic_mock() -> AsyncMock:
    """Build a mock LLM client that returns fixed, deterministic responses per role.

    - TARGET: "Hello! How can I help you today?"
    - JUDGE: {"score": 4, "reason": "Good greeting"}
    - META (critic): "The prompt is clear and well-structured."
    - META (author): revised template wrapped in delimiters
    """
    mock_client = AsyncMock(spec=LLMProvider)

    async def mock_chat_completion(messages, model, role, **kwargs):
        if role == ModelRole.TARGET:
            return _make_llm_response(
                content="Hello! How can I help you today?",
                role=ModelRole.TARGET,
            )

        if role == ModelRole.JUDGE:
            criteria = [
                line.split(". ", 1)[1]
                for line in messages[-1]["content"].split("## Criteria to Evaluate\n", 1)[1].splitlines()
                if line[:1].isdigit() and ". " in line
            ]
            return _make_llm_response(
                content=json.dumps({
                    "evaluations": [
                        {"criterion": criterion, "passed": False, "reason": "Needs refinement"}
                        for criterion in criteria
                    ]
                }),
                role=ModelRole.JUDGE,
            )

        if role == ModelRole.META:
            # Distinguish critic vs author by inspecting system message
            system_content = ""
            for m in messages:
                if m.get("role") == "system":
                    system_content = m.get("content", "")

            if "critic" in system_content.lower() or "evaluate" in system_content.lower():
                return _make_llm_response(
                    content="The prompt is clear and well-structured.",
                    role=ModelRole.META,
                )

            # Author call: return template with delimiters
            return _make_llm_response(
                content=f"<revised_template>\n{SIMPLE_TEMPLATE}\n</revised_template>",
                role=ModelRole.META,
            )

        # Fallback
        return _make_llm_response(content="fallback", role=role)

    mock_client.chat_completion = AsyncMock(side_effect=mock_chat_completion)
    mock_client.close = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    return mock_client


def _make_test_cases() -> list[TestCase]:
    """Create a simple test case list for pipeline regression testing.

    Uses behavior-only expectations (no tool_calls) to avoid the combined
    scoring path and keep the pipeline deterministic.
    """
    return [
        TestCase(
            id="greeting-test",
            name="Basic greeting",
            description="Verify the assistant greets the user politely",
            variables={"instruction": "Greet the user"},
            chat_history=[{"role": "user", "content": "Hello"}],
            expected_output={"behavior": ["Greets the user politely"]},
        ),
    ]


def _build_pipeline(mock_client: AsyncMock) -> tuple[IslandEvolver, CostTracker]:
    """Wire up the full evolution pipeline with minimal config for determinism.

    Returns:
        Tuple of (IslandEvolver, CostTracker) for assertions.
    """
    cost_tracker = CostTracker()

    renderer = TemplateRenderer()
    exact_scorer = ExactMatchScorer()
    behavior_scorer = BehaviorJudgeScorer(client=mock_client, judge_model="mock-judge")
    aggregator = FitnessAggregator()

    evaluator = FitnessEvaluator(
        client=mock_client,
        renderer=renderer,
        exact_scorer=exact_scorer,
        behavior_scorer=behavior_scorer,
        aggregator=aggregator,
        cost_tracker=cost_tracker,
    )

    validator = TemplateValidator()
    rcc = RCCEngine(
        client=mock_client,
        cost_tracker=cost_tracker,
        validator=validator,
        meta_model="mock-meta",
    )
    mutator = StructuralMutator(
        client=mock_client,
        cost_tracker=cost_tracker,
        validator=validator,
        meta_model="mock-meta",
    )
    selector = BoltzmannSelector()

    # Minimal config: 1 generation, 1 island, 1 conversation, 1 refinement turn
    evolution_config = EvolutionConfig(
        generations=1,
        n_islands=1,
        conversations_per_island=1,
        n_seq=1,
        n_parents=1,
        population_cap=5,
        structural_mutation_probability=0.0,
        n_seed_variants=0,  # Disable seed diversity for determinism
    )

    generation_config = GenerationConfig(temperature=0.7, max_tokens=1024)
    cases = _make_test_cases()

    evolver = IslandEvolver(
        config=evolution_config,
        evaluator=evaluator,
        rcc=rcc,
        mutator=mutator,
        selector=selector,
        cost_tracker=cost_tracker,
        original_template=SIMPLE_TEMPLATE,
        anchor_variables=set(),
        cases=cases,
        target_model="mock-target",
        generation_config=generation_config,
        prompt_tools=None,
        purpose="Greet users politely",
    )

    return evolver, cost_tracker


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelineRegression:
    """Deterministic evolution pipeline regression tests."""

    # -- Test 1: Deterministic fitness across repeated runs --

    async def test_deterministic_fitness_across_runs(self):
        """Two consecutive runs with identical config produce the same best fitness score."""
        mock1 = _build_deterministic_mock()
        evolver1, _ = _build_pipeline(mock1)
        result1 = await evolver1.run()

        mock2 = _build_deterministic_mock()
        evolver2, _ = _build_pipeline(mock2)
        result2 = await evolver2.run()

        assert result1.best_candidate.fitness_score == result2.best_candidate.fitness_score
        assert result1.best_candidate.fitness_score is not None

    # -- Test 2: Correct termination reason --

    async def test_termination_reason(self):
        """Evolution result has correct termination_reason."""
        mock_client = _build_deterministic_mock()
        evolver, _ = _build_pipeline(mock_client)
        result = await evolver.run()

        # With 1 generation and mock responses, should terminate normally
        assert result.termination_reason in (
            "generations_complete",
            "perfect_fitness",
            "budget_exhausted",
        )

    # -- Test 3: CostTracker records expected API calls --

    async def test_cost_tracker_records_calls(self):
        """CostTracker records API calls after evolution run."""
        mock_client = _build_deterministic_mock()
        evolver, cost_tracker = _build_pipeline(mock_client)
        await evolver.run()

        summary = cost_tracker.summary()
        assert summary["total_calls"] > 0
        assert summary["total_cost_usd"] > 0

    # -- Test 4: Mock client receives calls for all 3 roles --

    async def test_all_roles_dispatched(self):
        """Mock client receives chat_completion calls for TARGET, JUDGE, and META roles."""
        mock_client = _build_deterministic_mock()
        evolver, _ = _build_pipeline(mock_client)
        await evolver.run()

        # Collect all roles from calls
        roles_used = set()
        for call in mock_client.chat_completion.call_args_list:
            # role can be positional arg [2] or keyword
            if "role" in call.kwargs:
                roles_used.add(call.kwargs["role"])
            elif len(call.args) >= 3:
                roles_used.add(call.args[2])

        assert ModelRole.TARGET in roles_used, "TARGET role not dispatched"
        assert ModelRole.JUDGE in roles_used, "JUDGE role not dispatched"
        assert ModelRole.META in roles_used, "META role not dispatched"

    # -- Test 5: Full pipeline wiring verification --

    async def test_pipeline_wiring(self):
        """Pipeline wires through all components: evaluator, RCC, selector, cost tracker."""
        mock_client = _build_deterministic_mock()
        evolver, cost_tracker = _build_pipeline(mock_client)
        result = await evolver.run()

        # Evaluator produced a result with a valid candidate
        assert result is not None
        assert result.best_candidate is not None
        assert result.best_candidate.template is not None
        assert len(result.best_candidate.template) > 0

        # RCC generated variant candidates (mock client was called for META role)
        meta_calls = [
            call
            for call in mock_client.chat_completion.call_args_list
            if call.kwargs.get("role") == ModelRole.META
            or (len(call.args) >= 3 and call.args[2] == ModelRole.META)
        ]
        assert len(meta_calls) > 0, "RCC engine did not generate any META calls"

        # Cost tracker aggregated calls from all components
        summary = cost_tracker.summary()
        assert summary["total_calls"] > 0

        # Selector ran (population management happened -- no crash, result produced)
        assert result.best_candidate.fitness_score is not None
