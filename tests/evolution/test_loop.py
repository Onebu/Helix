"""Integration tests for EvolutionLoop orchestrator.

Tests cover the full evolution loop with mocked components:
- Single/multi generation completion
- Early termination on perfect fitness (score == 0.0)
- Budget cap and per-conversation budget checks (COST-03)
- Per-generation cost tracking (COST-02)
- Population cap enforcement
- Penalty-based population ranking (all candidates participate)
- Pr_no_parents fresh generation
- Probabilistic structural mutation
- Initial candidate evaluation
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from api.config.models import GenerationConfig
from api.dataset.models import TestCase
from api.evaluation.evaluator import FitnessEvaluator
from api.evaluation.models import (
    CaseResult,
    EvaluationInvalidError,
    EvaluationReport,
    FitnessScore,
)
from api.evolution.loop import EvolutionLoop
from api.evolution.models import Candidate, EvolutionConfig, GenerationRecord
from api.evolution.mutator import StructuralMutator
from api.evolution.rcc import RCCEngine
from api.evolution.selector import BoltzmannSelector
from api.gateway.cost import CostTracker
from api.lineage.collector import LineageCollector
from api.types import LLMResponse, ModelRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_report(score: float, rejected: bool = False) -> EvaluationReport:
    """Create an EvaluationReport with a controlled fitness score.

    Penalty model: 0.0 = perfect, negative = penalized.
    """
    return EvaluationReport(
        fitness=FitnessScore(
            score=score,
            rejected=rejected,
        ),
        case_results=[
            CaseResult(case_id="c1", score=score, passed=score == 0),
        ],
        total_cases=1,
        cost_summary={
            "total_calls": 1,
            "total_input_tokens": 10,
            "total_output_tokens": 10,
            "total_cost_usd": 0.001,
        },
    )


def _make_candidate(template: str = "evolved {{ x }}", generation: int = 0) -> Candidate:
    """Create a Candidate with a test template."""
    return Candidate(template=template, generation=generation, parent_ids=[])


def _make_population_candidate(
    template: str = "Hello {{ x }}",
    generation: int = 0,
    score: float = -2.0,
) -> Candidate:
    candidate = _make_candidate(template, generation)
    report = _make_report(score)
    candidate.fitness_score = report.fitness.score
    candidate.normalized_score = report.fitness.normalized_score
    candidate.rejected = report.fitness.rejected
    candidate.evaluation = report
    return candidate


def _make_llm_response(cost_usd: float = 0.001) -> LLMResponse:
    """Create a minimal LLMResponse for cost tracking."""
    return LLMResponse(
        content="ok",
        model_used="test/model",
        role=ModelRole.TARGET,
        input_tokens=10,
        output_tokens=10,
        cost_usd=cost_usd,
        timestamp=datetime.now(),
    )


def _build_loop(
    config: EvolutionConfig | None = None,
    evaluator: FitnessEvaluator | None = None,
    rcc: RCCEngine | None = None,
    mutator: StructuralMutator | None = None,
    cost_tracker: CostTracker | None = None,
) -> EvolutionLoop:
    """Build an EvolutionLoop with sensible defaults and optional overrides."""
    if config is None:
        config = EvolutionConfig(
            generations=1,
            conversations_per_island=2,
        rcc_rounds=1,
            n_parents=3,
            structural_mutation_probability=0.0,
            pr_no_parents=0.0,
        )
    if evaluator is None:
        evaluator = AsyncMock(spec=FitnessEvaluator)
        evaluator.evaluate = AsyncMock(return_value=_make_report(-2.0))
    if rcc is None:
        rcc = AsyncMock(spec=RCCEngine)
        rcc_count = 0

        async def unique_rcc(**kwargs):
            nonlocal rcc_count
            rcc_count += 1
            return [_make_candidate(template=f"evolved_{rcc_count} {{{{ x }}}}")]

        rcc.run_conversation = AsyncMock(side_effect=unique_rcc)
    if mutator is None:
        mutator = AsyncMock(spec=StructuralMutator)
        mutator.mutate = AsyncMock(return_value=_make_candidate())
    if cost_tracker is None:
        cost_tracker = CostTracker()

    return EvolutionLoop(
        config=config,
        evaluator=evaluator,
        rcc=rcc,
        mutator=mutator,
        selector=BoltzmannSelector(),
        cost_tracker=cost_tracker,
        original_template="Hello {{ x }}",
        anchor_variables={"x"},
        cases=[TestCase(id="c1", chat_history=[{"role": "user", "content": "hi"}])],
        target_model="test/model",
        generation_config=GenerationConfig(),
        purpose="test",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_generation_completes():
    """1 generation, 2 conversations -> EvolutionResult with generation_records."""
    loop = _build_loop()
    result = await loop.run()

    assert result.termination_reason == "generations_complete"
    assert len(result.generation_records) == 1
    assert result.generation_records[0].generation == 0
    assert result.generation_records[0].candidates_evaluated == 2
    assert result.best_candidate is not None


@pytest.mark.asyncio
async def test_early_termination_perfect_fitness():
    """Candidate with score 0.0 (perfect) terminates immediately."""
    evaluator = AsyncMock(spec=FitnessEvaluator)

    async def evaluate(**kwargs):
        score = 0.0 if kwargs["template"] == "evolved_1 {{ x }}" else -2.0
        return _make_report(score)

    evaluator.evaluate = AsyncMock(side_effect=evaluate)

    config = EvolutionConfig(
        generations=10,
        conversations_per_island=5,
        rcc_rounds=1,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )
    loop = _build_loop(config=config, evaluator=evaluator)
    result = await loop.run()

    assert result.termination_reason == "perfect_fitness"
    assert result.best_candidate.fitness_score == 0.0
    # Scouting is disabled, so every distinct draft receives a full evaluation.
    assert evaluator.evaluate.call_count == 1 + config.conversations_per_island


@pytest.mark.asyncio
async def test_budget_cap_terminates():
    """Cost exceeds budget_cap_usd -> termination_reason='budget_exhausted' (COST-03)."""
    cost_tracker = CostTracker()
    cost_tracker.record(_make_llm_response(cost_usd=5.0))

    config = EvolutionConfig(
        generations=5,
        conversations_per_island=3,
        rcc_rounds=1,
        budget_cap_usd=1.0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )

    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(-2.0))

    loop = _build_loop(config=config, evaluator=evaluator, cost_tracker=cost_tracker)
    result = await loop.run()

    assert result.termination_reason == "budget_exhausted"


@pytest.mark.asyncio
async def test_budget_checked_per_conversation():
    """Budget check happens before each conversation, not just per generation."""
    cost_tracker = CostTracker()

    evaluator = AsyncMock(spec=FitnessEvaluator)
    call_count = 0

    async def eval_with_cost(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            cost_tracker.record(_make_llm_response(cost_usd=10.0))
        return _make_report(-2.0)

    evaluator.evaluate = AsyncMock(side_effect=eval_with_cost)

    config = EvolutionConfig(
        generations=1,
        conversations_per_island=5,
        rcc_rounds=1,
        budget_cap_usd=1.0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )
    loop = _build_loop(config=config, evaluator=evaluator, cost_tracker=cost_tracker)
    result = await loop.run()

    assert result.termination_reason == "budget_exhausted"
    assert evaluator.evaluate.call_count < 1 + 5


@pytest.mark.asyncio
async def test_generation_cost_tracking():
    """Each GenerationRecord has cost_summary with per-generation costs (COST-02)."""
    cost_tracker = CostTracker()

    evaluator = AsyncMock(spec=FitnessEvaluator)
    call_count = 0

    async def eval_with_cost(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        cost_tracker.record(_make_llm_response(cost_usd=0.01))
        return _make_report(-2.0)

    evaluator.evaluate = AsyncMock(side_effect=eval_with_cost)

    config = EvolutionConfig(
        generations=2,
        conversations_per_island=2,
        rcc_rounds=1,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )
    loop = _build_loop(config=config, evaluator=evaluator, cost_tracker=cost_tracker)
    result = await loop.run()

    assert len(result.generation_records) == 2
    for record in result.generation_records:
        assert "total_cost_usd" in record.cost_summary
        assert "total_calls" in record.cost_summary
    gen0_cost = result.generation_records[0].cost_summary["total_cost_usd"]
    gen1_cost = result.generation_records[1].cost_summary["total_cost_usd"]
    assert gen0_cost > 0
    assert gen1_cost > 0


@pytest.mark.asyncio
async def test_population_capped():
    """Population never exceeds population_cap."""
    config = EvolutionConfig(
        generations=3,
        conversations_per_island=5,
        rcc_rounds=1,
        population_cap=3,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )

    evaluator = AsyncMock(spec=FitnessEvaluator)
    eval_count = 0

    async def varying_eval(*args, **kwargs):
        nonlocal eval_count
        eval_count += 1
        # Varying negative penalties, never reaching 0 (perfect)
        score = -0.5 - 0.1 * (eval_count % 10)
        return _make_report(score)

    evaluator.evaluate = AsyncMock(side_effect=varying_eval)

    rcc = AsyncMock(spec=RCCEngine)
    rcc_count = 0

    async def unique_rcc(*args, **kwargs):
        nonlocal rcc_count
        rcc_count += 1
        return [_make_candidate(template=f"evolved_{rcc_count} {{{{ x }}}}")]

    rcc.run_conversation = AsyncMock(side_effect=unique_rcc)

    loop = _build_loop(config=config, evaluator=evaluator, rcc=rcc)
    result = await loop.run()

    total_evaluated = sum(r.candidates_evaluated for r in result.generation_records)
    assert total_evaluated > 3
    assert result.termination_reason == "generations_complete"


@pytest.mark.asyncio
async def test_heavily_penalized_candidates_ranked_lower():
    """All candidates stay in population, but heavily penalized ones rank lower."""
    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(
        side_effect=[
            _make_report(-2.0),  # seed: penalty -2
            _make_report(-10.0),  # conv1: heavy penalty -10
            _make_report(-1.0),  # conv2: light penalty -1
        ]
    )

    config = EvolutionConfig(
        generations=1,
        conversations_per_island=2,
        rcc_rounds=1,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )
    loop = _build_loop(config=config, evaluator=evaluator)
    result = await loop.run()

    # Best candidate should have the least negative score
    assert result.best_candidate.fitness_score == -1.0


@pytest.mark.asyncio
@patch("api.evolution.loop.random")
async def test_pr_no_parents_fresh_generation(mock_random):
    """With pr_no_parents=1.0, all conversations get 0 parents."""
    config = EvolutionConfig(
        generations=1,
        conversations_per_island=3,
        rcc_rounds=1,
        pr_no_parents=1.0,
        structural_mutation_probability=0.0,
    )

    rcc = AsyncMock(spec=RCCEngine)
    rcc.run_conversation = AsyncMock(return_value=[_make_candidate()])

    mock_random.random.return_value = 0.5

    loop = _build_loop(config=config, rcc=rcc)
    await loop.run()

    for call_args in rcc.run_conversation.call_args_list:
        parents = call_args.kwargs.get("parents", call_args.args[0] if call_args.args else None)
        assert parents == []


@pytest.mark.asyncio
@patch("api.evolution.loop.random")
async def test_structural_mutation_applied_probabilistically(mock_random):
    """With probability 1.0, mutator is always called; with 0.0, never called."""
    mutator = AsyncMock(spec=StructuralMutator)
    mutator.mutate = AsyncMock(return_value=_make_candidate())

    mock_random.random.return_value = 0.0

    config_always = EvolutionConfig(
        generations=1,
        conversations_per_island=2,
        rcc_rounds=1,
        structural_mutation_probability=1.0,
        pr_no_parents=0.0,
    )
    mock_random.randint.return_value = 1

    loop = _build_loop(config=config_always, mutator=mutator)
    await loop.run()
    assert mutator.mutate.call_count == 2

    mutator.mutate.reset_mock()
    config_never = EvolutionConfig(
        generations=1,
        conversations_per_island=2,
        rcc_rounds=1,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )
    mock_random.randint.return_value = 1
    loop = _build_loop(config=config_never, mutator=mutator)
    await loop.run()
    assert mutator.mutate.call_count == 0


@pytest.mark.asyncio
async def test_multi_generation_evolution():
    """3+ generations, fitness improves over time (less negative)."""
    evaluator = AsyncMock(spec=FitnessEvaluator)
    call_count = 0

    async def improving_eval(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Start very negative, improve toward 0
        score = max(-10.0 + 1.0 * call_count, -0.5)
        return _make_report(score)

    evaluator.evaluate = AsyncMock(side_effect=improving_eval)

    config = EvolutionConfig(
        generations=3,
        conversations_per_island=2,
        rcc_rounds=1,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )
    loop = _build_loop(config=config, evaluator=evaluator)
    result = await loop.run()

    assert len(result.generation_records) == 3
    assert result.termination_reason == "generations_complete"
    best_gen0 = result.generation_records[0].best_fitness
    best_gen2 = result.generation_records[2].best_fitness
    assert best_gen2 >= best_gen0


@pytest.mark.asyncio
async def test_termination_reason_generations_complete():
    """All generations exhausted -> reason is 'generations_complete'."""
    config = EvolutionConfig(
        generations=2,
        conversations_per_island=1,
        rcc_rounds=1,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )
    loop = _build_loop(config=config)
    result = await loop.run()

    assert result.termination_reason == "generations_complete"
    assert len(result.generation_records) == 2


@pytest.mark.asyncio
async def test_initial_candidate_evaluated():
    """The original template is evaluated to establish baseline fitness."""
    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(-3.0))

    config = EvolutionConfig(
        generations=1,
        conversations_per_island=1,
        rcc_rounds=1,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )
    loop = _build_loop(config=config, evaluator=evaluator)
    await loop.run()

    assert evaluator.evaluate.call_count >= 2
    first_call_kwargs = evaluator.evaluate.call_args_list[0].kwargs
    assert first_call_kwargs["template"] == "Hello {{ x }}"


# ---------------------------------------------------------------------------
# step_generation() Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_generation_returns_tuple():
    """step_generation returns (list[Candidate], GenerationRecord, str|None) tuple."""
    loop = _build_loop()
    seed = _make_population_candidate()

    result = await loop.step_generation(population=[seed], generation=0)

    assert isinstance(result, tuple)
    assert len(result) == 3
    population, record, termination_reason = result
    assert isinstance(population, list)
    assert all(isinstance(c, Candidate) for c in population)
    assert isinstance(record, GenerationRecord)
    assert termination_reason is None


@pytest.mark.asyncio
async def test_step_generation_runs_conversations():
    """step_generation runs conversations_per_island conversations and adds new candidates."""
    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(-1.0))

    rcc = AsyncMock(spec=RCCEngine)
    rcc_count = 0

    async def unique_rcc(*args, **kwargs):
        nonlocal rcc_count
        rcc_count += 1
        return [_make_candidate(template=f"evolved_{rcc_count} {{{{ x }}}}")]

    rcc.run_conversation = AsyncMock(side_effect=unique_rcc)

    config = EvolutionConfig(
        generations=1,
        conversations_per_island=3,
        rcc_rounds=1,
        n_parents=3,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )
    loop = _build_loop(config=config, evaluator=evaluator, rcc=rcc)
    seed = _make_population_candidate()

    population, record, reason = await loop.step_generation(population=[seed], generation=0)

    assert rcc.run_conversation.call_count == 3
    assert evaluator.evaluate.call_count == 3
    assert len(population) >= 1
    assert record.candidates_evaluated == 3
    assert reason is None


@pytest.mark.asyncio
async def test_step_generation_perfect_fitness():
    """step_generation returns 'perfect_fitness' when candidate scores 0.0."""
    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(0.0))

    config = EvolutionConfig(
        generations=1,
        conversations_per_island=5,
        rcc_rounds=1,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )
    loop = _build_loop(config=config, evaluator=evaluator)
    seed = _make_population_candidate()

    _population, _record, reason = await loop.step_generation(population=[seed], generation=0)

    assert reason == "perfect_fitness"
    assert evaluator.evaluate.call_count == config.conversations_per_island


@pytest.mark.asyncio
async def test_step_generation_budget_exhausted():
    """step_generation returns 'budget_exhausted' when budget exceeded."""
    cost_tracker = CostTracker()
    cost_tracker.record(_make_llm_response(cost_usd=5.0))

    config = EvolutionConfig(
        generations=1,
        conversations_per_island=5,
        rcc_rounds=1,
        budget_cap_usd=1.0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )

    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(-2.0))

    loop = _build_loop(config=config, evaluator=evaluator, cost_tracker=cost_tracker)
    seed = _make_population_candidate()

    _population, _record, reason = await loop.step_generation(population=[seed], generation=0)

    assert reason == "budget_exhausted"


@pytest.mark.asyncio
async def test_step_generation_population_capped():
    """step_generation caps population at population_cap."""
    evaluator = AsyncMock(spec=FitnessEvaluator)
    eval_count = 0

    async def varying_eval(*args, **kwargs):
        nonlocal eval_count
        eval_count += 1
        # Varying negative penalties, never reaching 0 (perfect)
        score = -0.5 - 0.1 * (eval_count % 10)
        return _make_report(score)

    evaluator.evaluate = AsyncMock(side_effect=varying_eval)

    rcc = AsyncMock(spec=RCCEngine)
    rcc_count = 0

    async def unique_rcc(*args, **kwargs):
        nonlocal rcc_count
        rcc_count += 1
        return [_make_candidate(template=f"evolved_{rcc_count} {{{{ x }}}}")]

    rcc.run_conversation = AsyncMock(side_effect=unique_rcc)

    config = EvolutionConfig(
        generations=1,
        conversations_per_island=10,
        rcc_rounds=1,
        population_cap=3,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )
    loop = _build_loop(config=config, evaluator=evaluator, rcc=rcc)

    seeds = [
        _make_population_candidate(
            template=f"seed_{i} {{{{ x }}}}",
            score=-0.5 * i,
        )
        for i in range(5)
    ]

    population, _record, _reason = await loop.step_generation(population=seeds, generation=0)

    assert len(population) <= 3


def test_n_parents_zero_never_calls_randint() -> None:
    loop = _build_loop(
        config=EvolutionConfig(
            conversations_per_island=1,
            rcc_rounds=1,
            n_parents=0,
            pr_no_parents=0.0,
            structural_mutation_probability=0.0,
        )
    )

    with patch("api.evolution.loop.random") as mock_random:
        assert loop._sample_parent_count() == 0

    mock_random.randint.assert_not_called()


@pytest.mark.asyncio
async def test_structural_event_requires_changed_template() -> None:
    events: list[tuple[str, dict]] = []

    async def callback(event_type: str, data: dict) -> None:
        events.append((event_type, data))

    rcc = AsyncMock(spec=RCCEngine)
    rcc.run_conversation = AsyncMock(
        return_value=[Candidate(template="Draft {{ x }}", parent_ids=["parent"])]
    )
    mutator = AsyncMock(spec=StructuralMutator)
    mutator.mutate = AsyncMock(
        return_value=Candidate(template="Draft {{ x }}\n", parent_ids=["parent"])
    )
    loop = _build_loop(
        config=EvolutionConfig(
            conversations_per_island=1,
            rcc_rounds=1,
            structural_mutation_probability=1.0,
            pr_no_parents=0.0,
        ),
        rcc=rcc,
        mutator=mutator,
    )
    loop._event_callback = callback

    await loop.step_generation([_make_population_candidate("Seed {{ x }}")], 0)

    evaluated = [data for event, data in events if event == "candidate_evaluated"]
    assert evaluated[0]["mutation_type"] == "rcc"


@pytest.mark.asyncio
@pytest.mark.parametrize("has_partial_report", [False, True])
async def test_step_generation_rejects_population_without_exact_full_report(
    has_partial_report: bool,
) -> None:
    loop = _build_loop()
    incoming = _make_candidate("Incoming {{ x }}")
    if has_partial_report:
        incoming.evaluation = EvaluationReport(
            fitness=FitnessScore(score=-1.0),
            case_results=[CaseResult(case_id="other", score=-1.0, passed=False)],
            total_cases=1,
        )

    with pytest.raises(EvaluationInvalidError):
        await loop.step_generation([incoming], 0)

    loop._rcc.run_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_paper_rounds_and_structural_child_are_all_retained_and_recorded() -> None:
    events: list[tuple[str, dict]] = []
    returned_rounds: list[Candidate] = []

    async def callback(event_type: str, data: dict) -> None:
        events.append((event_type, data))

    async def paper_rcc(**kwargs):
        evaluate_draft = kwargs["evaluate_draft"]
        assert evaluate_draft is not None
        parent_ids = [parent.id for parent in kwargs["parents"]]
        for name in ("Round one {{ x }}", "Round two {{ x }}"):
            returned_rounds.append(
                await evaluate_draft(Candidate(template=name, parent_ids=parent_ids))
            )
        return returned_rounds

    async def mutate(candidate, *_args):
        return Candidate(
            template="Structural child {{ x }}",
            parent_ids=[candidate.id],
        )

    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(
        side_effect=[_make_report(-3.0), _make_report(-2.0), _make_report(-1.0)]
    )
    rcc = AsyncMock(spec=RCCEngine)
    rcc.run_conversation = AsyncMock(side_effect=paper_rcc)
    mutator = AsyncMock(spec=StructuralMutator)
    mutator.mutate = AsyncMock(side_effect=mutate)
    loop = _build_loop(
        config=EvolutionConfig(
            evolution_profile="paper_reference",
            conversations_per_island=1,
            rcc_rounds=2,
            structural_mutation_probability=1.0,
            pr_no_parents=0.0,
        ),
        evaluator=evaluator,
        rcc=rcc,
        mutator=mutator,
    )
    loop._event_callback = callback
    loop._collector = LineageCollector()

    population, record, _ = await loop.step_generation(
        [_make_population_candidate()],
        0,
    )

    templates = {candidate.template for candidate in population}
    assert templates >= {
        "Round one {{ x }}",
        "Round two {{ x }}",
        "Structural child {{ x }}",
    }
    assert evaluator.evaluate.call_count == 3
    assert record.candidates_evaluated == 3
    structural = next(
        candidate for candidate in population if candidate.template == "Structural child {{ x }}"
    )
    assert structural.parent_ids == [returned_rounds[-1].id]
    evaluated_events = [data for event, data in events if event == "candidate_evaluated"]
    assert len(evaluated_events) == 3
    assert [data["mutation_type"] for data in evaluated_events].count("structural") == 1
    structural_lineage = [
        event for event in loop._collector.events if event.mutation_type == "structural"
    ]
    assert len(structural_lineage) == 1
    assert structural_lineage[0].parent_ids == [returned_rounds[-1].id]


@pytest.mark.asyncio
async def test_paper_duplicate_callbacks_share_full_evaluation_before_population_dedup() -> None:
    callback_results: list[Candidate] = []

    async def duplicate_rcc(**kwargs):
        evaluated = await kwargs["evaluate_draft"](
            Candidate(template="Duplicate {{ x }}", parent_ids=["parent"])
        )
        callback_results.append(evaluated)
        return [evaluated]

    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(-1.0))
    rcc = AsyncMock(spec=RCCEngine)
    rcc.run_conversation = AsyncMock(side_effect=duplicate_rcc)
    loop = _build_loop(
        config=EvolutionConfig(
            evolution_profile="paper_reference",
            conversations_per_island=2,
            rcc_rounds=1,
            structural_mutation_probability=0.0,
            pr_no_parents=0.0,
        ),
        evaluator=evaluator,
        rcc=rcc,
    )

    population, record, _ = await loop.step_generation(
        [_make_population_candidate()],
        0,
    )

    assert len(callback_results) == 2
    assert all(candidate.evaluation is not None for candidate in callback_results)
    assert callback_results[0].evaluation is not callback_results[1].evaluation
    assert evaluator.evaluate.call_count == 1
    assert sum(candidate.template == "Duplicate {{ x }}" for candidate in population) == 1
    assert record.candidates_evaluated == 1


@pytest.mark.asyncio
async def test_step_generation_handles_reservation_rejection():
    tracker = CostTracker(budget_cap_usd=0.0000001)
    rcc = AsyncMock(spec=RCCEngine)

    async def reject_reservation(**_kwargs):
        await tracker.reserve("openai/gpt-4o-mini", 1, 1)

    rcc.run_conversation = AsyncMock(side_effect=reject_reservation)
    loop = _build_loop(
        config=EvolutionConfig(
            generations=1,
            conversations_per_island=1,
            rcc_rounds=1,
            n_parents=1,
            pr_no_parents=0.0,
            structural_mutation_probability=0.0,
            budget_cap_usd=0.0000001,
        ),
        rcc=rcc,
        cost_tracker=tracker,
    )

    updated, _record, reason = await loop.step_generation(
        [_make_population_candidate()], generation=0
    )

    assert reason == "budget_exhausted"
    assert updated[0].evaluation is not None
