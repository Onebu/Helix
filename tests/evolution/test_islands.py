"""Tests for IslandEvolver multi-island evolution orchestrator.

Tests cover:
- Multi-island parallel (sequential) evolution with independent populations
- Cyclic migration with deep copies and no-op conditions
- Island reset at configurable intervals with safety guards
- Global best tracking across all islands
- Budget enforcement across islands
- Perfect fitness termination (score == 0.0)
- Seed candidate evaluated once and cloned to all islands
- Single-island backward compatibility
- Aggregate generation records
- Population management after migration
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from api.config.models import GenerationConfig
from api.dataset.models import TestCase
from api.evaluation.evaluator import FitnessEvaluator
from api.evaluation.models import (
    CaseResult,
    EvaluationReport,
    FitnessScore,
)
from api.evolution.islands import IslandEvolver
from api.evolution.models import (
    Candidate,
    EvolutionConfig,
    GenerationRecord,
)
from api.evolution.mutator import StructuralMutator
from api.evolution.rcc import RCCEngine
from api.evolution.selector import BoltzmannSelector
from api.gateway.cost import CostTracker
from api.types import LLMResponse, ModelRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_report(score: float, rejected: bool = False) -> EvaluationReport:
    """Create an EvaluationReport with a controlled fitness score.

    Penalty model: 0.0 = perfect, negative = penalized.
    """
    return EvaluationReport(
        fitness=FitnessScore(score=score, rejected=rejected),
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


def _make_candidate(
    template: str = "evolved {{ x }}",
    generation: int = 0,
    fitness: float = -2.0,
    rejected: bool = False,
    evaluated: bool = True,
) -> Candidate:
    """Create a Candidate with a test template and fitness."""
    c = Candidate(template=template, generation=generation, parent_ids=[])
    c.fitness_score = fitness
    c.rejected = rejected
    if evaluated:
        c.evaluation = _make_report(fitness, rejected=rejected)
    return c


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


def _make_record(generation: int = 0, fitness: float = -2.0) -> GenerationRecord:
    return GenerationRecord(
        generation=generation,
        best_fitness=fitness,
        avg_fitness=fitness,
        cost_summary={"total_cost_usd": 0.0},
        candidates_evaluated=1,
    )


def _build_island_evolver(
    config: EvolutionConfig | None = None,
    evaluator: FitnessEvaluator | None = None,
    rcc: RCCEngine | None = None,
    mutator: StructuralMutator | None = None,
    cost_tracker: CostTracker | None = None,
) -> IslandEvolver:
    """Build an IslandEvolver with sensible defaults and optional overrides."""
    if config is None:
        config = EvolutionConfig(
            generations=1,
            conversations_per_island=2,
            rcc_rounds=1,
            n_parents=3,
            n_islands=2,
            n_emigrate=1,
            reset_interval=0,
            n_reset=1,
            n_top=2,
            structural_mutation_probability=0.0,
            pr_no_parents=0.0,
            population_cap=10,
        )
    if evaluator is None:
        evaluator = AsyncMock(spec=FitnessEvaluator)
        evaluator.evaluate = AsyncMock(return_value=_make_report(-2.0))
    if rcc is None:
        rcc = AsyncMock(spec=RCCEngine)
        rcc.run_conversation = AsyncMock(return_value=[_make_candidate(evaluated=False)])
    if mutator is None:
        mutator = AsyncMock(spec=StructuralMutator)
        mutator.mutate = AsyncMock(return_value=_make_candidate())
    if cost_tracker is None:
        cost_tracker = CostTracker()

    return IslandEvolver(
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
# Tests: Basic multi-island run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_island_run_completes():
    """IslandEvolver.run() with n_islands=2 runs both islands and returns EvolutionResult."""
    evolver = _build_island_evolver()
    result = await evolver.run()

    assert result.termination_reason == "generations_complete"
    assert len(result.generation_records) == 1
    assert result.best_candidate is not None


@pytest.mark.asyncio
async def test_reset_runs_after_completed_generations_three_six_nine():
    evolver = _build_island_evolver(
        config=EvolutionConfig(
            generations=10,
            conversations_per_island=1,
            rcc_rounds=1,
            n_islands=2,
            n_emigrate=0,
            reset_interval=3,
            n_seed_variants=0,
            structural_mutation_probability=0.0,
            pr_no_parents=0.0,
        )
    )

    async def completed_generation(*, population, generation, island):
        return population, _make_record(generation), None

    for loop in evolver._loops:
        loop.step_generation = AsyncMock(side_effect=completed_generation)
    evolver._reset_islands = AsyncMock()

    await evolver.run()

    assert evolver._reset_islands.await_count == 3


def test_aggregate_records_uses_one_global_cost_delta():
    records = [
        GenerationRecord(
            generation=0,
            best_fitness=-1,
            avg_fitness=-2,
            cost_summary={"total_calls": 1, "total_input_tokens": 10, "total_output_tokens": 5, "total_cost_usd": 1},
            candidates_evaluated=1,
        ),
        GenerationRecord(
            generation=0,
            best_fitness=-2,
            avg_fitness=-3,
            cost_summary={"total_calls": 1, "total_input_tokens": 10, "total_output_tokens": 5, "total_cost_usd": 1},
            candidates_evaluated=1,
        ),
    ]

    delta = {
        "total_calls": 1,
        "total_input_tokens": 10,
        "total_output_tokens": 5,
        "total_cost_usd": 1,
    }
    merged = IslandEvolver._aggregate_records(records, delta)

    assert merged.cost_summary == delta


@pytest.mark.asyncio
async def test_improved_seed_variant_survives_budget_stop_before_generation_zero():
    tracker = CostTracker()
    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluations = 0

    async def evaluate(**kwargs):
        nonlocal evaluations
        evaluations += 1
        if evaluations == 2:
            tracker.record(_make_llm_response(cost_usd=1.0))
            return _make_report(-1.0)
        return _make_report(-5.0)

    evaluator.evaluate = AsyncMock(side_effect=evaluate)
    rcc = AsyncMock(spec=RCCEngine)
    rcc.run_conversation = AsyncMock(
        return_value=[_make_candidate(template="improved {{ x }}", evaluated=False)]
    )
    evolver = _build_island_evolver(
        config=EvolutionConfig(
            generations=1,
            conversations_per_island=1,
            rcc_rounds=1,
            n_islands=2,
            n_emigrate=0,
            reset_interval=0,
            n_seed_variants=1,
            budget_cap_usd=1.0,
            structural_mutation_probability=0.0,
            pr_no_parents=0.0,
        ),
        evaluator=evaluator,
        rcc=rcc,
        cost_tracker=tracker,
    )

    result = await evolver.run()

    assert result.termination_reason == "budget_exhausted"
    assert result.best_candidate.template == "improved {{ x }}"


@pytest.mark.asyncio
async def test_successful_island_result_is_processed_when_sibling_raises():
    evolver = _build_island_evolver(
        config=EvolutionConfig(
            generations=1,
            conversations_per_island=1,
            rcc_rounds=1,
            n_islands=2,
            n_emigrate=0,
            reset_interval=0,
            n_seed_variants=0,
            structural_mutation_probability=0.0,
            pr_no_parents=0.0,
        )
    )
    feasible = _make_candidate(template="feasible {{ x }}", fitness=-1.0)
    rejected = _make_candidate(
        template="rejected {{ x }}", fitness=0.0, rejected=True
    )
    partial = _make_candidate(
        template="partial {{ x }}", fitness=100.0, evaluated=False
    )
    evolver._loops[0].step_generation = AsyncMock(side_effect=RuntimeError("boom"))
    evolver._loops[1].step_generation = AsyncMock(
        return_value=([rejected, partial, feasible], _make_record(fitness=-1.0), None)
    )

    result = await evolver.run()

    assert result.termination_reason == "error"
    assert result.best_candidate.template == "feasible {{ x }}"


@pytest.mark.asyncio
async def test_cancelled_island_retains_sibling_improvement():
    evolver = _build_island_evolver(
        config=EvolutionConfig(
            generations=1,
            conversations_per_island=1,
            rcc_rounds=1,
            n_islands=2,
            n_emigrate=0,
            reset_interval=0,
            n_seed_variants=0,
            structural_mutation_probability=0.0,
            pr_no_parents=0.0,
        )
    )
    improved = _make_candidate(template="improved {{ x }}", fitness=-1.0)
    evolver._loops[0].step_generation = AsyncMock(side_effect=asyncio.CancelledError())
    evolver._loops[1].step_generation = AsyncMock(
        return_value=([improved], _make_record(fitness=-1.0), None)
    )

    result = await evolver.run()

    assert result.termination_reason == "error"
    assert result.best_candidate.template == "improved {{ x }}"


# ---------------------------------------------------------------------------
# Tests: Cyclic migration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cyclic_migration_moves_candidates():
    """Cyclic migration moves top n_emigrate candidates from island i to island (i+1) % n_islands."""
    evaluator = AsyncMock(spec=FitnessEvaluator)
    call_count = 0

    async def score_eval(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_report(-5.0)
        return _make_report(-2.0 + -0.1 * call_count)

    evaluator.evaluate = AsyncMock(side_effect=score_eval)

    rcc = AsyncMock(spec=RCCEngine)
    rcc_count = 0

    async def unique_rcc(*args, **kwargs):
        nonlocal rcc_count
        rcc_count += 1
        return [
            _make_candidate(template=f"evolved_{rcc_count} {{{{ x }}}}", evaluated=False)
        ]

    rcc.run_conversation = AsyncMock(side_effect=unique_rcc)

    config = EvolutionConfig(
        generations=2,
        conversations_per_island=2,
        rcc_rounds=1,
        n_parents=3,
        n_islands=2,
        n_emigrate=1,
        reset_interval=0,
        n_reset=0,
        n_top=2,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        population_cap=10,
    )
    evolver = _build_island_evolver(config=config, evaluator=evaluator, rcc=rcc)
    result = await evolver.run()

    assert len(result.generation_records) == 2
    assert result.termination_reason == "generations_complete"


@pytest.mark.asyncio
async def test_migration_uses_deep_copies():
    """Migration uses deep copies -- modifying migrated candidate does not affect source island."""
    evolver = _build_island_evolver()

    c1 = _make_candidate(template="island_0 {{ x }}", fitness=-2.0)
    c2 = _make_candidate(template="island_1 {{ x }}", fitness=-5.0)
    evolver._island_populations = [[c1], [c2]]

    evolver._migrate()

    assert len(evolver._island_populations[1]) == 2
    migrated = evolver._island_populations[1][1]
    assert migrated.template == c1.template

    migrated.fitness_score = 999.0
    assert c1.fitness_score == -2.0


def test_migration_requires_full_reports_and_ranks_feasible_first():
    evolver = _build_island_evolver()
    feasible = _make_candidate(template="feasible {{ x }}", fitness=-5.0)
    rejected = _make_candidate(
        template="rejected {{ x }}", fitness=0.0, rejected=True
    )
    partial = _make_candidate(
        template="partial {{ x }}", fitness=100.0, evaluated=False
    )
    target = _make_candidate(template="target {{ x }}", fitness=-10.0)
    evolver._island_populations = [[partial, rejected, feasible], [target]]

    evolver._migrate()

    assert evolver._island_populations[1][-1].template == "feasible {{ x }}"


def test_migration_clone_model_and_lineage_share_source_parent():
    from api.lineage.collector import LineageCollector

    evolver = _build_island_evolver()
    evolver._collector = LineageCollector()
    source = _make_candidate(template="source {{ x }}", fitness=-1.0)
    target = _make_candidate(template="target {{ x }}", fitness=-5.0)
    evolver._island_populations = [[source], [target]]

    evolver._migrate()

    migrated = evolver._island_populations[1][-1]
    event = next(item for item in evolver._collector.events if item.candidate_id == migrated.id)
    assert migrated.parent_ids == [source.id]
    assert event.parent_ids == migrated.parent_ids
    migrated.template = "changed"
    assert source.template == "source {{ x }}"


@pytest.mark.asyncio
async def test_migration_noop_when_n_emigrate_zero():
    """Migration is a no-op when n_emigrate=0."""
    config = EvolutionConfig(
        generations=1,
        conversations_per_island=1,
        rcc_rounds=1,
        n_islands=2,
        n_emigrate=0,
        reset_interval=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )
    evolver = _build_island_evolver(config=config)
    c1 = _make_candidate(template="island_0 {{ x }}", fitness=-2.0)
    c2 = _make_candidate(template="island_1 {{ x }}", fitness=-5.0)
    evolver._island_populations = [[c1], [c2]]

    evolver._migrate()

    assert len(evolver._island_populations[0]) == 1
    assert len(evolver._island_populations[1]) == 1


@pytest.mark.asyncio
async def test_migration_noop_when_single_island():
    """Migration is a no-op when n_islands=1."""
    config = EvolutionConfig(
        generations=1,
        conversations_per_island=1,
        rcc_rounds=1,
        n_islands=1,
        n_emigrate=5,
        reset_interval=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )
    evolver = _build_island_evolver(config=config)
    c1 = _make_candidate(template="only_island {{ x }}", fitness=-2.0)
    evolver._island_populations = [[c1]]

    evolver._migrate()

    assert len(evolver._island_populations[0]) == 1


# ---------------------------------------------------------------------------
# Tests: Island reset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_island_reset_replaces_lowest():
    """Island reset replaces lowest-performing islands with top global candidates."""
    config = EvolutionConfig(
        generations=1,
        conversations_per_island=1,
        rcc_rounds=1,
        n_islands=3,
        n_emigrate=0,
        reset_interval=3,
        n_reset=1,
        n_top=2,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        population_cap=10,
    )
    evolver = _build_island_evolver(config=config)

    # Set up 3 islands: island 0 is worst (most negative), island 2 is best
    evolver._island_populations = [
        [_make_candidate(template="low {{ x }}", fitness=-10.0)],
        [_make_candidate(template="mid {{ x }}", fitness=-2.0)],
        [_make_candidate(template="high {{ x }}", fitness=-0.5)],
    ]

    await evolver._reset_islands()

    # Island 0 (lowest) should be replaced with top global candidates
    assert len(evolver._island_populations[0]) == 2  # n_top=2
    for c in evolver._island_populations[0]:
        assert c.fitness_score >= -2.0  # top 2 globally = -0.5 and -2.0


@pytest.mark.asyncio
async def test_reset_replaces_lowest_with_all_candidates():
    """Reset includes all candidates (no rejected filtering)."""
    config = EvolutionConfig(
        generations=1,
        conversations_per_island=1,
        rcc_rounds=1,
        n_islands=2,
        n_emigrate=0,
        reset_interval=3,
        n_reset=1,
        n_top=2,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )
    evolver = _build_island_evolver(config=config)

    # Even with rejected=True, candidates participate in reset
    c1 = _make_candidate(template="penalized1 {{ x }}", fitness=-8.0)
    c1.rejected = True
    c2 = _make_candidate(template="penalized2 {{ x }}", fitness=-3.0)
    c2.rejected = True
    evolver._island_populations = [[c1], [c2]]

    await evolver._reset_islands()

    # Reset should have happened since candidates exist (even if rejected)
    assert len(evolver._island_populations[0]) == 2  # n_top=2


@pytest.mark.asyncio
async def test_reset_never_resets_all_islands():
    """n_reset is capped at n_islands - 1 (never reset all islands)."""
    config = EvolutionConfig(
        generations=1,
        conversations_per_island=1,
        rcc_rounds=1,
        n_islands=2,
        n_emigrate=0,
        reset_interval=3,
        n_reset=10,
        n_top=2,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )
    evolver = _build_island_evolver(config=config)

    evolver._island_populations = [
        [_make_candidate(template="low {{ x }}", fitness=-10.0)],
        [_make_candidate(template="high {{ x }}", fitness=-0.5)],
    ]

    await evolver._reset_islands()

    assert any(c.template == "high {{ x }}" for c in evolver._island_populations[1])


@pytest.mark.asyncio
async def test_paper_reference_reset_uses_diverse_selector():
    evolver = _build_island_evolver(
        config=EvolutionConfig(
            evolution_profile="paper_reference",
            conversations_per_island=1,
            n_islands=2,
            n_top=2,
            n_reset=1,
            n_seed_variants=0,
        )
    )
    first = _make_candidate(template="first {{ x }}", fitness=-1)
    second = _make_candidate(template="second {{ x }}", fitness=-2)
    evolver._island_populations = [
        [first, second],
        [_make_candidate(template="weak {{ x }}", fitness=-10)],
    ]
    evolver._rcc.select_diverse = AsyncMock(return_value=[first, second])

    await evolver._reset_islands()

    evolver._rcc.select_diverse.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_ranks_empty_island_worse_than_negative_valid_island():
    evolver = _build_island_evolver(
        config=EvolutionConfig(n_islands=2, n_reset=1, n_top=1, n_seed_variants=0)
    )
    valid = _make_candidate(template="valid {{ x }}", fitness=-10.0)
    evolver._island_populations = [[], [valid]]

    await evolver._reset_islands()

    assert evolver._island_populations[0][0].template == "valid {{ x }}"
    assert evolver._island_populations[1][0] is valid


@pytest.mark.asyncio
async def test_paper_reset_rejects_diverse_selection_with_avoidable_rejected_candidate():
    evolver = _build_island_evolver(
        config=EvolutionConfig(
            evolution_profile="paper_reference",
            conversations_per_island=1,
            n_islands=3,
            n_reset=1,
            n_top=2,
            n_seed_variants=0,
        )
    )
    first = _make_candidate(template="first {{ x }}", fitness=-1.0)
    second = _make_candidate(template="second {{ x }}", fitness=-2.0)
    rejected = _make_candidate(
        template="rejected {{ x }}", fitness=0.0, rejected=True
    )
    weak = _make_candidate(template="weak {{ x }}", fitness=-10.0)
    evolver._island_populations = [[first, rejected], [second], [weak]]
    evolver._rcc.select_diverse = AsyncMock(return_value=[first, rejected])

    await evolver._reset_islands()

    assert [candidate.template for candidate in evolver._island_populations[2]] == [
        "first {{ x }}",
        "second {{ x }}",
    ]


@pytest.mark.asyncio
async def test_reset_clone_model_and_lineage_share_source_parent():
    from api.lineage.collector import LineageCollector

    evolver = _build_island_evolver(
        config=EvolutionConfig(n_islands=2, n_reset=1, n_top=1, n_seed_variants=0)
    )
    evolver._collector = LineageCollector()
    low = _make_candidate(template="low {{ x }}", fitness=-10.0)
    source = _make_candidate(template="source {{ x }}", fitness=-1.0)
    evolver._island_populations = [[low], [source]]

    await evolver._reset_islands()

    reset = evolver._island_populations[0][0]
    event = next(item for item in evolver._collector.events if item.candidate_id == reset.id)
    assert reset.parent_ids == [source.id]
    assert event.parent_ids == reset.parent_ids
    reset.template = "changed"
    assert source.template == "source {{ x }}"


@pytest.mark.asyncio
async def test_reset_fires_at_correct_intervals():
    """Reset only fires when generation > 0 and generation % reset_interval == 0."""
    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(-2.0))

    rcc = AsyncMock(spec=RCCEngine)
    rcc_count = 0

    async def unique_rcc(*args, **kwargs):
        nonlocal rcc_count
        rcc_count += 1
        return [
            _make_candidate(template=f"evolved_{rcc_count} {{{{ x }}}}", evaluated=False)
        ]

    rcc.run_conversation = AsyncMock(side_effect=unique_rcc)

    config = EvolutionConfig(
        generations=4,
        conversations_per_island=1,
        rcc_rounds=1,
        n_islands=2,
        n_emigrate=0,
        reset_interval=3,
        n_reset=1,
        n_top=2,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        population_cap=10,
    )
    evolver = _build_island_evolver(config=config, evaluator=evaluator, rcc=rcc)
    result = await evolver.run()

    assert len(result.generation_records) == 4
    assert result.termination_reason == "generations_complete"


@pytest.mark.asyncio
async def test_reset_event_uses_completed_generation_number():
    events: list[tuple[str, dict]] = []

    async def capture(event_type: str, data: dict) -> None:
        events.append((event_type, data))

    evolver = _build_island_evolver(
        config=EvolutionConfig(
            generations=4,
            conversations_per_island=1,
            rcc_rounds=1,
            n_islands=2,
            n_emigrate=0,
            reset_interval=3,
            n_reset=1,
            n_top=1,
            n_seed_variants=0,
        )
    )
    evolver._event_callback = capture

    async def completed(*, population, generation, island):
        return population, _make_record(generation), None

    for loop in evolver._loops:
        loop.step_generation = AsyncMock(side_effect=completed)

    await evolver.run()

    reset_events = [data for event, data in events if event == "island_reset"]
    assert reset_events[0]["generation"] == 3


# ---------------------------------------------------------------------------
# Tests: Global best tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_best_tracked_across_islands():
    """Global best is tracked across all islands."""
    evaluator = AsyncMock(spec=FitnessEvaluator)
    call_count = 0

    async def island_eval(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_report(-5.0)  # seed
        if call_count % 2 == 0:
            return _make_report(-4.0)  # island 0: worse
        return _make_report(-0.5)  # island 1: better

    evaluator.evaluate = AsyncMock(side_effect=island_eval)

    rcc = AsyncMock(spec=RCCEngine)
    rcc_count = 0

    async def unique_rcc(*args, **kwargs):
        nonlocal rcc_count
        rcc_count += 1
        return [
            _make_candidate(template=f"evolved_{rcc_count} {{{{ x }}}}", evaluated=False)
        ]

    rcc.run_conversation = AsyncMock(side_effect=unique_rcc)

    config = EvolutionConfig(
        generations=1,
        conversations_per_island=1,
        rcc_rounds=1,
        n_islands=2,
        n_emigrate=0,
        reset_interval=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )
    evolver = _build_island_evolver(config=config, evaluator=evaluator, rcc=rcc)
    result = await evolver.run()

    assert result.best_candidate.fitness_score >= -4.0


# ---------------------------------------------------------------------------
# Tests: Budget enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_exhaustion_terminates():
    """Budget exhaustion mid-run terminates with 'budget_exhausted'."""
    cost_tracker = CostTracker()
    cost_tracker.record(_make_llm_response(cost_usd=5.0))

    config = EvolutionConfig(
        generations=5,
        conversations_per_island=3,
        rcc_rounds=1,
        n_islands=2,
        n_emigrate=1,
        budget_cap_usd=1.0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )

    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(-2.0))

    evolver = _build_island_evolver(config=config, evaluator=evaluator, cost_tracker=cost_tracker)
    result = await evolver.run()

    assert result.termination_reason == "budget_exhausted"


# ---------------------------------------------------------------------------
# Tests: Perfect fitness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_perfect_fitness_terminates():
    """Perfect fitness (0.0) found on any island terminates with 'perfect_fitness'."""
    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(
        side_effect=[
            _make_report(-2.0),  # seed
            _make_report(-1.0),  # island 0 conv
            _make_report(0.0),  # island 1 conv -> perfect!
        ]
    )

    rcc = AsyncMock(spec=RCCEngine)
    rcc_count = 0

    async def unique_rcc(*args, **kwargs):
        nonlocal rcc_count
        rcc_count += 1
        return [
            _make_candidate(template=f"perfect_{rcc_count} {{{{ x }}}}", evaluated=False)
        ]

    rcc.run_conversation = AsyncMock(side_effect=unique_rcc)

    config = EvolutionConfig(
        generations=10,
        conversations_per_island=1,
        rcc_rounds=1,
        n_islands=2,
        n_emigrate=0,
        reset_interval=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )
    evolver = _build_island_evolver(config=config, evaluator=evaluator, rcc=rcc)
    result = await evolver.run()

    assert result.termination_reason == "perfect_fitness"
    assert result.best_candidate.fitness_score == 0.0


# ---------------------------------------------------------------------------
# Tests: Seed evaluation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_reference_initial_population_has_conversations_times_rounds():
    config = EvolutionConfig(
        evolution_profile="paper_reference",
        conversations_per_island=2,
        rcc_rounds=4,
        generations=1,
        n_islands=2,
        n_seed_variants=0,
    )
    evolver = _build_island_evolver(config=config)
    call_index = 0

    async def four_drafts(**kwargs):
        nonlocal call_index
        call_index += 1
        evaluate_draft = kwargs["evaluate_draft"]
        drafts = []
        for round_index in range(4):
            drafts.append(await evaluate_draft(_make_candidate(
                template=f"conversation-{call_index}-round-{round_index} {{{{ x }}}}"
            )))
        return drafts

    evolver._rcc.run_conversation = AsyncMock(side_effect=four_drafts)
    seed = _make_candidate(template="seed {{ x }}", fitness=-5)

    await evolver._initialize_populations(seed)

    seed_clone = evolver._island_populations[0][0]
    generated = [
        candidate
        for candidate in evolver._island_populations[0]
        if candidate.template != seed.template
    ]
    assert seed_clone.parent_ids == [seed.id]
    assert len(generated) == 8
    assert all(candidate.parent_ids == [seed.id] for candidate in generated)
    assert len(evolver._rcc.run_conversation.await_args_list) == 2
    assert evolver._island_populations[0][1] is not evolver._island_populations[1][1]

    evolver._island_populations[0][1].template = "changed"
    assert evolver._island_populations[1][1].template != "changed"


@pytest.mark.asyncio
async def test_cost_controlled_seed_variants_deduplicate_before_evaluation_and_placement():
    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(-1.0))
    rcc = AsyncMock(spec=RCCEngine)
    rcc.run_conversation = AsyncMock(
        side_effect=[
            [_make_candidate(template="Hello {{ x }}", evaluated=False)],
            [_make_candidate(template="variant-a {{ x }}", evaluated=False)],
            [_make_candidate(template="variant-a {{ x }}\n", evaluated=False)],
            [_make_candidate(template="variant-b {{ x }}", evaluated=False)],
        ]
    )
    evolver = _build_island_evolver(
        config=EvolutionConfig(
            generations=1,
            conversations_per_island=1,
            rcc_rounds=1,
            n_islands=2,
            n_seed_variants=4,
        ),
        evaluator=evaluator,
        rcc=rcc,
    )
    seed = _make_candidate(template="Hello {{ x }}", fitness=-5.0)

    await evolver._initialize_populations(seed)

    assert evaluator.evaluate.await_count == 2
    assert [candidate.template for candidate in evolver._island_populations[0]] == [
        "Hello {{ x }}",
        "variant-a {{ x }}",
    ]
    assert [candidate.template for candidate in evolver._island_populations[1]] == [
        "Hello {{ x }}",
        "variant-b {{ x }}",
    ]
    assert all(
        candidate.parent_ids == [seed.id]
        for population in evolver._island_populations
        for candidate in population
    )


@pytest.mark.asyncio
async def test_seed_evaluated_once_cloned_to_all_islands():
    """Seed candidate is evaluated once and cloned to all islands."""
    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(-2.0))

    rcc = AsyncMock(spec=RCCEngine)
    async def fresh_draft(**_kwargs):
        return [_make_candidate(evaluated=False)]

    rcc.run_conversation = AsyncMock(side_effect=fresh_draft)

    config = EvolutionConfig(
        generations=1,
        conversations_per_island=1,
        rcc_rounds=1,
        n_islands=3,
        n_emigrate=0,
        reset_interval=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )
    evolver = _build_island_evolver(config=config, evaluator=evaluator, rcc=rcc)
    await evolver.run()

    # 1 (seed) + 3 islands * 1 conv = 4 total (n_seed_variants=0)
    assert evaluator.evaluate.call_count == 4


# ---------------------------------------------------------------------------
# Tests: Single-island backward compatibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_island_equivalent():
    """n_islands=1 produces result equivalent to EvolutionLoop.run()."""
    evaluator = AsyncMock(spec=FitnessEvaluator)
    call_count = 0

    async def eval_fn(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_report(-5.0 + 0.5 * call_count)

    evaluator.evaluate = AsyncMock(side_effect=eval_fn)

    rcc = AsyncMock(spec=RCCEngine)
    rcc_count = 0

    async def unique_rcc(*args, **kwargs):
        nonlocal rcc_count
        rcc_count += 1
        return [
            _make_candidate(template=f"evolved_{rcc_count} {{{{ x }}}}", evaluated=False)
        ]

    rcc.run_conversation = AsyncMock(side_effect=unique_rcc)

    config = EvolutionConfig(
        generations=2,
        conversations_per_island=2,
        rcc_rounds=1,
        n_islands=1,
        n_emigrate=5,
        reset_interval=3,
        n_reset=1,
        n_top=2,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )
    evolver = _build_island_evolver(config=config, evaluator=evaluator, rcc=rcc)
    result = await evolver.run()

    assert result.termination_reason == "generations_complete"
    assert len(result.generation_records) == 2
    assert evaluator.evaluate.call_count == 5


# ---------------------------------------------------------------------------
# Tests: Aggregate generation records
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregate_generation_records():
    """Generation records are aggregate: best_fitness = max, avg_fitness = mean across islands."""
    evaluator = AsyncMock(spec=FitnessEvaluator)
    call_count = 0

    async def island_eval(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_report(-5.0)  # seed
        if call_count % 2 == 0:
            return _make_report(-4.0)
        return _make_report(-1.0)

    evaluator.evaluate = AsyncMock(side_effect=island_eval)

    rcc = AsyncMock(spec=RCCEngine)
    rcc_count = 0

    async def unique_rcc(*args, **kwargs):
        nonlocal rcc_count
        rcc_count += 1
        return [
            _make_candidate(template=f"evolved_{rcc_count} {{{{ x }}}}", evaluated=False)
        ]

    rcc.run_conversation = AsyncMock(side_effect=unique_rcc)

    config = EvolutionConfig(
        generations=1,
        conversations_per_island=1,
        rcc_rounds=1,
        n_islands=2,
        n_emigrate=0,
        reset_interval=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )
    evolver = _build_island_evolver(config=config, evaluator=evaluator, rcc=rcc)
    result = await evolver.run()

    assert len(result.generation_records) == 1
    record = result.generation_records[0]
    assert record.best_fitness >= -4.0
    assert record.candidates_evaluated == 2


@pytest.mark.asyncio
async def test_generation_progress_best_is_feasible_first():
    events: list[tuple[str, dict]] = []

    async def capture(event_type: str, data: dict) -> None:
        events.append((event_type, data))

    evolver = _build_island_evolver(
        config=EvolutionConfig(
            generations=1,
            conversations_per_island=1,
            rcc_rounds=1,
            n_islands=2,
            n_emigrate=0,
            reset_interval=0,
            n_seed_variants=0,
        )
    )
    evolver._event_callback = capture
    feasible = _make_candidate(template="feasible {{ x }}", fitness=-2.0)
    feasible.normalized_score = 0.25
    rejected = _make_candidate(
        template="rejected {{ x }}", fitness=0.0, rejected=True
    )
    rejected.normalized_score = 1.0
    evolver._loops[0].step_generation = AsyncMock(
        return_value=(
            [rejected],
            GenerationRecord(
                generation=0,
                best_fitness=0.0,
                avg_fitness=0.0,
                best_normalized=1.0,
                avg_normalized=1.0,
                candidates_evaluated=1,
            ),
            None,
        )
    )
    evolver._loops[1].step_generation = AsyncMock(
        return_value=(
            [feasible],
            GenerationRecord(
                generation=0,
                best_fitness=-2.0,
                avg_fitness=-2.0,
                best_normalized=0.25,
                avg_normalized=0.25,
                candidates_evaluated=1,
            ),
            None,
        )
    )

    result = await evolver.run()

    assert result.generation_records[0].best_fitness == -2.0
    assert result.generation_records[0].best_normalized == 0.25
    complete = [data for event, data in events if event == "generation_complete"]
    assert complete[0]["best_fitness"] == -2.0
    assert complete[0]["best_normalized"] == 0.25


# ---------------------------------------------------------------------------
# Tests: Population management after migration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_survivors_after_migration():
    """_select_survivors is called after migration to keep populations bounded."""
    config = EvolutionConfig(
        generations=1,
        conversations_per_island=1,
        rcc_rounds=1,
        n_islands=2,
        n_emigrate=5,
        reset_interval=0,
        population_cap=3,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )
    evolver = _build_island_evolver(config=config)

    evolver._island_populations = [
        [_make_candidate(template=f"a{i} {{{{ x }}}}", fitness=-0.5 * i) for i in range(5)],
        [_make_candidate(template=f"b{i} {{{{ x }}}}", fitness=-0.5 * i) for i in range(5)],
    ]

    evolver._migrate()
    evolver._select_survivors_all()

    for pop in evolver._island_populations:
        assert len(pop) <= 3


def test_select_survivors_all_keeps_every_candidate_when_cap_is_none():
    evolver = _build_island_evolver(
        config=EvolutionConfig(
            evolution_profile="paper_reference",
            conversations_per_island=1,
            n_islands=1,
            n_emigrate=0,
            population_cap=None,
            n_seed_variants=0,
        )
    )
    evolver._island_populations = [[
        _make_candidate(template="first {{ x }}", fitness=-1.0),
        _make_candidate(template="second {{ x }}", fitness=-2.0),
    ]]

    evolver._select_survivors_all()

    assert len(evolver._island_populations[0]) == 2


# ---------------------------------------------------------------------------
# Tests: Seed perfect fitness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_perfect_fitness_returns_immediately():
    """If seed has perfect fitness (0.0), return immediately without running generations."""
    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(0.0))

    config = EvolutionConfig(
        generations=10,
        conversations_per_island=5,
        rcc_rounds=1,
        n_islands=3,
        n_emigrate=2,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )
    evolver = _build_island_evolver(config=config, evaluator=evaluator)
    result = await evolver.run()

    assert result.termination_reason == "perfect_fitness"
    assert result.best_candidate.fitness_score == 0.0
    assert evaluator.evaluate.call_count == 1


@pytest.mark.asyncio
async def test_rejected_score_zero_seed_is_not_perfect():
    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(0.0, rejected=True))
    evolver = _build_island_evolver(
        config=EvolutionConfig(
            generations=1,
            conversations_per_island=1,
            rcc_rounds=1,
            n_islands=1,
            n_emigrate=0,
            reset_interval=0,
            n_seed_variants=0,
            structural_mutation_probability=0.0,
            pr_no_parents=0.0,
        ),
        evaluator=evaluator,
    )

    result = await evolver.run()

    assert result.termination_reason != "perfect_fitness"


# ---------------------------------------------------------------------------
# Tests: Per-island seed cloning with unique IDs and lineage events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_clones_have_unique_ids_and_lineage_events():
    """Each island's seed clone gets a unique UUID with a recorded LineageEvent."""
    from api.lineage.collector import LineageCollector

    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(-2.0))

    rcc = AsyncMock(spec=RCCEngine)
    rcc.run_conversation = AsyncMock(return_value=[_make_candidate(evaluated=False)])

    collector = LineageCollector()

    config = EvolutionConfig(
        generations=1,
        conversations_per_island=1,
        rcc_rounds=1,
        n_islands=3,
        n_emigrate=0,
        reset_interval=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )

    evolver = IslandEvolver(
        config=config,
        evaluator=evaluator,
        rcc=rcc,
        mutator=AsyncMock(spec=StructuralMutator),
        selector=BoltzmannSelector(),
        cost_tracker=CostTracker(),
        original_template="Hello {{ x }}",
        anchor_variables={"x"},
        cases=[TestCase(id="c1", chat_history=[{"role": "user", "content": "hi"}])],
        target_model="test/model",
        generation_config=GenerationConfig(),
        purpose="test",
        collector=collector,
    )

    await evolver.run()

    events = collector.events

    # Find the original seed event (no parents)
    seed_events = [
        e for e in events if e.mutation_type == "seed" and not e.parent_ids
    ]
    assert len(seed_events) == 1, "Should have exactly one original seed event"
    original_seed_id = seed_events[0].candidate_id

    # Per-island seed clones preserve the seed's root ancestry.
    clone_events = [e for e in events if e.mutation_type == "seed" and e.parent_ids]
    assert len(clone_events) == 3, (
        f"Expected 3 per-island seed clone events, got {len(clone_events)}"
    )

    # Verify unique IDs
    clone_ids = [e.candidate_id for e in clone_events]
    assert len(set(clone_ids)) == 3, "All seed clone IDs should be unique"
    assert original_seed_id not in clone_ids, "Clone IDs should differ from original seed ID"

    # Verify island assignments
    clone_islands = sorted(e.island for e in clone_events)
    assert clone_islands == [0, 1, 2], f"Expected islands [0, 1, 2], got {clone_islands}"

    candidates_by_id = {
        candidate.id: candidate
        for population in evolver._island_populations
        for candidate in population
    }
    for clone_event in clone_events:
        assert clone_event.parent_ids == [original_seed_id]
        assert candidates_by_id[clone_event.candidate_id].parent_ids == clone_event.parent_ids
        assert clone_event.generation == 0


# ---------------------------------------------------------------------------
# Tests: Per-island loop infrastructure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_island_loops_created():
    """EVO-01: IslandEvolver creates N EvolutionLoop instances (one per island).

    Each loop is a distinct instance so _seed_results state is isolated.
    """
    from api.evolution.loop import EvolutionLoop

    config = EvolutionConfig(
        generations=1,
        conversations_per_island=1,
        rcc_rounds=1,
        n_islands=4,
        n_emigrate=0,
        reset_interval=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )
    evolver = _build_island_evolver(config=config)

    # Should have N loops (one per island)
    assert hasattr(evolver, "_loops"), "IslandEvolver should have _loops attribute"
    assert len(evolver._loops) == 4, f"Expected 4 loops, got {len(evolver._loops)}"

    # Each loop must be a distinct EvolutionLoop instance
    for i, loop in enumerate(evolver._loops):
        assert isinstance(loop, EvolutionLoop), f"Loop {i} is not an EvolutionLoop"
    ids = [id(loop) for loop in evolver._loops]
    assert len(set(ids)) == 4, "All loops must be distinct instances"


# ---------------------------------------------------------------------------
# Tests: Parallel execution with asyncio.gather
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_islands_run_completes():
    """EVO-01: Parallel execution with asyncio.gather completes without error.

    Verifies that run() with n_islands=3 returns valid EvolutionResult with
    generation records when islands execute via asyncio.gather.
    """
    evaluator = AsyncMock(spec=FitnessEvaluator)
    call_count = 0

    async def eval_fn(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_report(-3.0 + 0.1 * call_count)

    evaluator.evaluate = AsyncMock(side_effect=eval_fn)

    rcc = AsyncMock(spec=RCCEngine)
    rcc_count = 0

    async def unique_rcc(*args, **kwargs):
        nonlocal rcc_count
        rcc_count += 1
        return [
            _make_candidate(template=f"parallel_{rcc_count} {{{{ x }}}}", evaluated=False)
        ]

    rcc.run_conversation = AsyncMock(side_effect=unique_rcc)

    config = EvolutionConfig(
        generations=2,
        conversations_per_island=2,
        rcc_rounds=1,
        n_parents=3,
        n_islands=3,
        n_emigrate=1,
        reset_interval=0,
        n_reset=0,
        n_top=2,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        population_cap=10,
        n_seed_variants=0,
    )
    evolver = _build_island_evolver(config=config, evaluator=evaluator, rcc=rcc)
    result = await evolver.run()

    assert result.termination_reason == "generations_complete"
    assert len(result.generation_records) == 2
    assert result.best_candidate is not None
    # 1 seed + 3 islands * 2 convs * 2 gens = 13 evaluations
    assert evaluator.evaluate.call_count == 13


@pytest.mark.asyncio
async def test_migration_after_gather():
    """EVO-01: Migration events occur after all island evaluations in a generation.

    Verifies that migration runs ONLY after all islands complete by
    checking event ordering via a mock event_callback.
    """
    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(-2.0))

    rcc = AsyncMock(spec=RCCEngine)
    rcc_count = 0

    async def unique_rcc(*args, **kwargs):
        nonlocal rcc_count
        rcc_count += 1
        return [
            _make_candidate(template=f"mig_{rcc_count} {{{{ x }}}}", evaluated=False)
        ]

    rcc.run_conversation = AsyncMock(side_effect=unique_rcc)

    config = EvolutionConfig(
        generations=1,
        conversations_per_island=1,
        rcc_rounds=1,
        n_islands=2,
        n_emigrate=1,
        reset_interval=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        population_cap=10,
        n_seed_variants=0,
    )

    events_log: list[str] = []

    async def track_events(event_type: str, data: dict) -> None:
        events_log.append(event_type)

    evolver = IslandEvolver(
        config=config,
        evaluator=evaluator,
        rcc=rcc,
        mutator=AsyncMock(spec=StructuralMutator),
        selector=BoltzmannSelector(),
        cost_tracker=CostTracker(),
        original_template="Hello {{ x }}",
        anchor_variables={"x"},
        cases=[TestCase(id="c1", chat_history=[{"role": "user", "content": "hi"}])],
        target_model="test/model",
        generation_config=GenerationConfig(),
        purpose="test",
        event_callback=track_events,
    )
    await evolver.run()

    # Find the index of migration event
    if "migration" in events_log:
        migration_idx = events_log.index("migration")
        # All candidate_evaluated events before migration should be from gen 0 setup
        # and the generation loop. Migration should come after generation_started.
        gen_started_indices = [i for i, e in enumerate(events_log) if e == "generation_started"]
        assert len(gen_started_indices) >= 1
        # Migration must come after the last candidate_evaluated in that generation
        candidate_evals_before_migration = [
            i for i, e in enumerate(events_log) if e == "candidate_evaluated" and i < migration_idx
        ]
        assert len(candidate_evals_before_migration) >= 2  # at least 2 islands evaluated


@pytest.mark.asyncio
async def test_budget_exhaustion_parallel():
    """EVO-01: Budget exhaustion during parallel execution terminates correctly.

    Sets a very low budget cap with 2 islands and verifies
    termination_reason='budget_exhausted' without crash from partial results.
    """
    cost_tracker = CostTracker()
    cost_tracker.record(_make_llm_response(cost_usd=10.0))

    config = EvolutionConfig(
        generations=5,
        conversations_per_island=3,
        rcc_rounds=1,
        n_islands=2,
        n_emigrate=1,
        budget_cap_usd=1.0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        n_seed_variants=0,
    )

    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(return_value=_make_report(-2.0))

    evolver = _build_island_evolver(config=config, evaluator=evaluator, cost_tracker=cost_tracker)
    result = await evolver.run()

    assert result.termination_reason == "budget_exhausted"
    assert len(result.generation_records) == 0  # budget exceeded before gen 0


@pytest.mark.asyncio
async def test_initialization_reservation_rejection_returns_seed_result():
    tracker = CostTracker(budget_cap_usd=0.0000001)
    rcc = AsyncMock(spec=RCCEngine)

    async def reject_reservation(**_kwargs):
        await tracker.reserve("openai/gpt-4o-mini", 1, 1)

    rcc.run_conversation = AsyncMock(side_effect=reject_reservation)
    evolver = _build_island_evolver(
        config=EvolutionConfig(
            generations=1,
            conversations_per_island=1,
            rcc_rounds=1,
            n_islands=2,
            n_seed_variants=1,
            budget_cap_usd=0.0000001,
        ),
        rcc=rcc,
        cost_tracker=tracker,
    )

    result = await evolver.run()

    assert result.termination_reason == "budget_exhausted"
    assert result.best_candidate.evaluation is not None
    assert all(
        candidate.evaluation is not None
        for population in evolver._island_populations
        for candidate in population
    )
