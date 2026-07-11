"""Benchmark tests for adaptive sampling API call reduction.

Verifies BENCH-02: adaptive sampling reduces the number of evaluated test cases
compared to full evaluation on consecutive-pass generations.

Tests:
1. Adaptive sampling reduces eval cases over consecutive all-pass generations
2. Adaptive sampling uses fewer total API calls than full evaluation
3. AdaptiveSampler weights decay monotonically with pass streaks
"""

from __future__ import annotations

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
from api.evolution.loop import EvolutionLoop
from api.evolution.models import Candidate, EvolutionConfig
from api.evolution.mutator import StructuralMutator
from api.evolution.rcc import RCCEngine
from api.evolution.selector import BoltzmannSelector
from api.gateway.cost import CostTracker

pytestmark = pytest.mark.benchmark


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cases(n: int) -> list[TestCase]:
    """Create n test cases with unique IDs."""
    return [
        TestCase(
            id=f"case-{i}",
            chat_history=[{"role": "user", "content": f"test {i}"}],
        )
        for i in range(n)
    ]


def _make_candidate(template: str = "evolved {{ x }}", generation: int = 0) -> Candidate:
    """Create a Candidate with a test template."""
    return Candidate(template=template, generation=generation, parent_ids=[])


def _make_all_pass_report(case_ids: list[str], score: float = -1.0) -> EvaluationReport:
    """Create an EvaluationReport where ALL cases pass."""
    return EvaluationReport(
        fitness=FitnessScore(score=score),
        case_results=[CaseResult(case_id=cid, score=0.8, passed=True) for cid in case_ids],
        total_cases=len(case_ids),
        cost_summary={
            "total_calls": 1,
            "total_input_tokens": 10,
            "total_output_tokens": 10,
            "total_cost_usd": 0.001,
        },
    )


def _build_fresh_loop(
    config: EvolutionConfig,
    evaluator: FitnessEvaluator,
    cases: list[TestCase],
) -> EvolutionLoop:
    """Build an EvolutionLoop with FRESH mocks to avoid state leakage."""
    rcc = AsyncMock(spec=RCCEngine)
    draft_index = 0

    async def unique_draft(**_kwargs):
        nonlocal draft_index
        draft_index += 1
        return [_make_candidate(template=f"evolved-{draft_index} {{{{ x }}}}")]

    rcc.run_conversation = AsyncMock(side_effect=unique_draft)

    mutator = AsyncMock(spec=StructuralMutator)
    mutator.mutate = AsyncMock(return_value=_make_candidate())

    return EvolutionLoop(
        config=config,
        evaluator=evaluator,
        rcc=rcc,
        mutator=mutator,
        selector=BoltzmannSelector(),
        cost_tracker=CostTracker(),
        original_template="Hello {{ x }}",
        anchor_variables={"x"},
        cases=cases,
        target_model="test/model",
        generation_config=GenerationConfig(),
        purpose="benchmark",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adaptive_sampling_reduces_eval_cases():
    """Adaptive sampling evaluates fewer cases as pass streaks grow.

    With all cases passing every generation, adaptive weights decay and
    smart_subset picks fewer passing cases over time.
    """
    cases = _make_cases(10)
    case_ids = [c.id for c in cases]

    config = EvolutionConfig(
        generations=4,
        conversations_per_island=1,
        n_seq=1,
        sample_size=3,
        adaptive_sampling=True,
        checkpoint_interval=0,  # Disabled -- no full-eval checkpoints
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )

    # Track how many cases the evaluator receives per call
    eval_case_counts: list[int] = []

    async def tracking_evaluate(**kwargs):
        received_cases = kwargs["cases"]
        eval_case_counts.append(len(received_cases))
        received_ids = [c.id for c in received_cases]
        return _make_all_pass_report(received_ids)

    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(side_effect=tracking_evaluate)

    loop = _build_fresh_loop(config=config, evaluator=evaluator, cases=cases)

    # Inject seed results so sampling is active
    seed_results = [CaseResult(case_id=cid, score=0.8, passed=True) for cid in case_ids]
    loop.set_seed_results(seed_results)

    seed = _make_candidate(template="Hello {{ x }}", generation=0)
    seed.fitness_score = -1.0
    seed.evaluation = _make_all_pass_report(case_ids)

    # Run 4 generations
    population = [seed]
    for gen in range(4):
        population, _record, _reason = await loop.step_generation(
            population=population, generation=gen
        )

    # Print summary table
    print("\n--- Adaptive Sampling: Eval Cases per Generation ---")
    for gen, count in enumerate(eval_case_counts):
        print(f"  Gen {gen}: {count} cases evaluated")

    # Each generation scouts on a subset, then fully verifies the promoted draft.
    scout_counts = eval_case_counts[::2]
    assert len(scout_counts) == 4
    assert all(count < len(cases) for count in scout_counts)


@pytest.mark.asyncio
async def test_adaptive_vs_full_eval_total_calls():
    """Adaptive sampling uses fewer total case evaluations than full eval.

    Runs the same 3-generation scenario with full eval (adaptive=False) and
    adaptive sampling (adaptive=True, sample_size=3) and compares totals.
    """
    cases = _make_cases(10)
    case_ids = [c.id for c in cases]

    # --- Full eval run ---
    full_eval_counts: list[int] = []

    async def full_tracking_evaluate(**kwargs):
        received_cases = kwargs["cases"]
        full_eval_counts.append(len(received_cases))
        received_ids = [c.id for c in received_cases]
        return _make_all_pass_report(received_ids)

    full_config = EvolutionConfig(
        generations=3,
        conversations_per_island=3,
        n_seq=1,
        adaptive_sampling=False,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )

    full_evaluator = AsyncMock(spec=FitnessEvaluator)
    full_evaluator.evaluate = AsyncMock(side_effect=full_tracking_evaluate)
    full_loop = _build_fresh_loop(config=full_config, evaluator=full_evaluator, cases=cases)

    full_seed = _make_candidate(template="Hello {{ x }}", generation=0)
    full_seed.fitness_score = -1.0
    full_seed.evaluation = _make_all_pass_report(case_ids)
    population = [full_seed]
    for gen in range(3):
        population, _record, _reason = await full_loop.step_generation(
            population=population, generation=gen
        )
    full_total = sum(full_eval_counts)

    # --- Adaptive run ---
    adaptive_eval_counts: list[int] = []

    async def adaptive_tracking_evaluate(**kwargs):
        received_cases = kwargs["cases"]
        adaptive_eval_counts.append(len(received_cases))
        received_ids = [c.id for c in received_cases]
        return _make_all_pass_report(received_ids)

    adaptive_config = EvolutionConfig(
        generations=3,
        conversations_per_island=3,
        n_seq=1,
        adaptive_sampling=True,
        sample_size=3,
        checkpoint_interval=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )

    adaptive_evaluator = AsyncMock(spec=FitnessEvaluator)
    adaptive_evaluator.evaluate = AsyncMock(side_effect=adaptive_tracking_evaluate)
    adaptive_loop = _build_fresh_loop(
        config=adaptive_config, evaluator=adaptive_evaluator, cases=cases
    )

    # Inject seed results for adaptive sampling
    seed_results = [CaseResult(case_id=cid, score=0.8, passed=True) for cid in case_ids]
    adaptive_loop.set_seed_results(seed_results)

    adaptive_seed = _make_candidate(template="Hello {{ x }}", generation=0)
    adaptive_seed.fitness_score = -1.0
    adaptive_seed.evaluation = _make_all_pass_report(case_ids)
    population = [adaptive_seed]
    for gen in range(3):
        population, _record, _reason = await adaptive_loop.step_generation(
            population=population, generation=gen
        )
    adaptive_total = sum(adaptive_eval_counts)

    # Print comparison
    reduction_pct = (1 - adaptive_total / full_total) * 100 if full_total > 0 else 0.0
    print("\n--- Full vs Adaptive Eval Comparison ---")
    print(
        f"  Full eval: {full_total} cases, Adaptive: {adaptive_total} cases, "
        f"Reduction: {reduction_pct:.1f}%"
    )

    # Assert: adaptive uses fewer total evaluations
    assert adaptive_total < full_total, (
        f"Adaptive ({adaptive_total}) should evaluate fewer cases than full eval ({full_total})"
    )


@pytest.mark.asyncio
async def test_adaptive_sampler_weights_decay_with_streaks():
    """AdaptiveSampler weights decrease monotonically as pass streaks grow.

    After multiple all-pass generations, cases with high streaks should have
    progressively lower sampling weights.
    """
    cases = _make_cases(5)
    case_ids = [c.id for c in cases]

    config = EvolutionConfig(
        generations=5,
        conversations_per_island=1,
        n_seq=1,
        sample_size=2,
        adaptive_sampling=True,
        checkpoint_interval=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )

    async def all_pass_evaluate(**kwargs):
        received_cases = kwargs["cases"]
        received_ids = [c.id for c in received_cases]
        return _make_all_pass_report(received_ids)

    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(side_effect=all_pass_evaluate)

    loop = _build_fresh_loop(config=config, evaluator=evaluator, cases=cases)

    # Inject seed results
    seed_results = [CaseResult(case_id=cid, score=0.8, passed=True) for cid in case_ids]
    loop.set_seed_results(seed_results)

    seed = _make_candidate(template="Hello {{ x }}", generation=0)
    seed.fitness_score = -1.0
    seed.evaluation = _make_all_pass_report(case_ids)

    # Track weights per generation
    weights_per_gen: list[dict[str, float]] = []

    population = [seed]
    for gen in range(5):
        population, _record, _reason = await loop.step_generation(
            population=population, generation=gen
        )
        # Read weights from the sampler after each generation
        assert loop._adaptive_sampler is not None
        weights = loop._adaptive_sampler.get_weights(cases)
        weights_per_gen.append(weights)

    # Print per-generation weights summary
    print("\n--- Adaptive Weights per Generation ---")
    for gen, weights in enumerate(weights_per_gen):
        weight_str = ", ".join(f"{cid}={w:.3f}" for cid, w in sorted(weights.items()))
        print(f"  Gen {gen}: {weight_str}")

    # Assert: weights decrease monotonically for each case
    for cid in case_ids:
        for gen in range(1, len(weights_per_gen)):
            assert weights_per_gen[gen][cid] <= weights_per_gen[gen - 1][cid], (
                f"Weight for {cid} increased from gen {gen - 1} "
                f"({weights_per_gen[gen - 1][cid]:.3f}) to gen {gen} "
                f"({weights_per_gen[gen][cid]:.3f})"
            )

    # Assert: after 5 generations, at least one case has decayed below 1.0.
    # With sample_size=2 out of 5 cases, not every case is sampled each
    # generation, so streaks vary.  We just verify decay is happening.
    final_weights = weights_per_gen[-1]
    min_weight = min(final_weights.values())
    assert min_weight < 1.0, (
        f"After 5 generations, minimum weight is {min_weight:.3f} "
        f"(expected < 1.0 — adaptive decay should have kicked in)"
    )
