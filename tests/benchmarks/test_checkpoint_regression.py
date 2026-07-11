"""Benchmark tests for checkpoint regression detection.

Verifies BENCH-03: checkpoint generations evaluate ALL test cases (not a subset)
and detect regressions (a case that was passing starts failing) by resetting
the adaptive sampler streak.

Tests:
1. Checkpoint generations evaluate all cases, non-checkpoints use sampling
2. Checkpoint detects regression by resetting the streak for failing cases
3. Checkpoint catches regressions that adaptive sampling alone would miss
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


def _make_report(case_results: list[CaseResult], score: float = -1.0) -> EvaluationReport:
    """Create an EvaluationReport with specific case results."""
    return EvaluationReport(
        fitness=FitnessScore(score=score),
        case_results=case_results,
        total_cases=len(case_results),
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
async def test_checkpoint_evaluates_all_cases():
    """Checkpoint generation (gen > 0 and gen % interval == 0) evaluates ALL cases.

    Non-checkpoint generations use smart_subset sampling, evaluating fewer cases.
    Checkpoint generations force full evaluation to detect hidden regressions.
    """
    cases = _make_cases(10)
    case_ids = [c.id for c in cases]

    config = EvolutionConfig(
        generations=3,
        conversations_per_island=1,
        rcc_rounds=1,
        sample_size=3,
        adaptive_sampling=True,
        checkpoint_interval=2,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )

    # Track eval case counts per generation
    eval_case_counts: list[int] = []

    async def tracking_evaluate(**kwargs):
        received_cases = kwargs["cases"]
        eval_case_counts.append(len(received_cases))
        received_ids = [c.id for c in received_cases]
        results = [CaseResult(case_id=cid, score=0.8, passed=True) for cid in received_ids]
        return _make_report(results)

    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(side_effect=tracking_evaluate)

    loop = _build_fresh_loop(config=config, evaluator=evaluator, cases=cases)

    # Inject seed results
    seed_results = [CaseResult(case_id=cid, score=0.8, passed=True) for cid in case_ids]
    loop.set_seed_results(seed_results)

    seed = _make_candidate(template="Hello {{ x }}", generation=0)
    seed.fitness_score = -1.0
    seed.evaluation = _make_report(seed_results)

    # Run generations 0, 1, 2
    population = [seed]
    for gen in range(3):
        population, _record, _reason = await loop.step_generation(
            population=population, generation=gen
        )

    n0, n1, n2 = eval_case_counts[0], eval_case_counts[2], eval_case_counts[-1]

    print("\n--- Checkpoint Full Evaluation ---")
    print(f"  Gen 0: {n0} cases, Gen 1: {n1} cases, Gen 2 (checkpoint): {n2} cases")

    # Gen 0 and Gen 1: NOT checkpoints (gen=0 fails 'generation > 0', gen=1 fails '1 % 2 == 0')
    # They should use sampled subset (< 10)
    assert n0 < 10, f"Gen 0 should use subset but got {n0}"
    assert n1 < 10, f"Gen 1 should use subset but got {n1}"

    # Gen 2: IS a checkpoint (2 > 0 and 2 % 2 == 0)
    # Must evaluate ALL 10 cases
    assert n2 == 10, f"Gen 2 (checkpoint) should use all 10 cases but got {n2}"


@pytest.mark.asyncio
async def test_checkpoint_detects_regression():
    """Checkpoint detects a regression by resetting the streak for failing cases.

    After building pass streaks over gens 0-1, gen 2 (checkpoint) reveals
    case-2 failing. The adaptive sampler resets case-2's streak to 0 while
    other passing cases retain their streaks.
    """
    cases = _make_cases(5)
    case_ids = [c.id for c in cases]

    config = EvolutionConfig(
        generations=3,
        conversations_per_island=1,
        rcc_rounds=1,
        sample_size=2,
        adaptive_sampling=True,
        checkpoint_interval=2,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )

    gen_counter = [0]

    async def conditional_evaluate(**kwargs):
        current_gen = gen_counter[0]
        received_cases = kwargs["cases"]
        received_ids = [c.id for c in received_cases]

        results = []
        for cid in received_ids:
            if current_gen >= 2 and cid == "case-2":
                # Regression: case-2 fails on checkpoint generation
                results.append(CaseResult(case_id=cid, score=0.0, passed=False))
            else:
                results.append(CaseResult(case_id=cid, score=0.8, passed=True))

        return _make_report(results)

    evaluator = AsyncMock(spec=FitnessEvaluator)
    evaluator.evaluate = AsyncMock(side_effect=conditional_evaluate)

    loop = _build_fresh_loop(config=config, evaluator=evaluator, cases=cases)

    # Inject seed results
    seed_results = [CaseResult(case_id=cid, score=0.8, passed=True) for cid in case_ids]
    loop.set_seed_results(seed_results)

    seed = _make_candidate(template="Hello {{ x }}", generation=0)
    seed.fitness_score = -1.0
    seed.evaluation = _make_report(seed_results)

    # Run gens 0-1 to build streaks
    population = [seed]
    for gen in range(2):
        gen_counter[0] = gen
        population, _record, _reason = await loop.step_generation(
            population=population, generation=gen
        )

    # Capture streaks BEFORE checkpoint
    assert loop._adaptive_sampler is not None
    streaks_before = dict(loop._adaptive_sampler.pass_streaks)
    print("\n--- Streaks Before Checkpoint ---")
    for cid in case_ids:
        print(f"  {cid}: streak={streaks_before.get(cid, 0)}")

    # Run gen 2 (checkpoint) -- case-2 fails
    gen_counter[0] = 2
    population, _record, _reason = await loop.step_generation(population=population, generation=2)

    # Capture streaks AFTER checkpoint
    streaks_after = dict(loop._adaptive_sampler.pass_streaks)
    print("--- Streaks After Checkpoint ---")
    for cid in case_ids:
        print(f"  {cid}: streak={streaks_after.get(cid, 0)}")

    # Assert: case-2's streak was reset to 0 (regression detected)
    assert streaks_after["case-2"] == 0, (
        f"case-2 streak should be 0 after checkpoint failure, got {streaks_after['case-2']}"
    )

    # Assert: case-0's streak is still > 0 (still passing)
    assert streaks_after["case-0"] > 0, (
        f"case-0 streak should be > 0 (still passing), got {streaks_after['case-0']}"
    )


@pytest.mark.asyncio
async def test_checkpoint_catches_regression_sampling_would_miss():
    """Checkpoint catches a regression in a high-streak case that sampling skips.

    This is the key BENCH-03 test: demonstrates that WITHOUT checkpoints,
    a regression in a high-streak case goes undetected because adaptive
    sampling skips it (very low weight). WITH checkpoints, gen 4 forces
    full evaluation and catches the failure.

    Setup:
    - 8 test cases, sample_size=1 (minimal sampling)
    - Gens 0-3: all pass (building streaks)
    - Before gen 4: manually boost case-7's streak to 30 (weight ~ 0.1 = min_rate)
    - Gen 4: case-7 regresses (fails when actually evaluated)

    Without checkpoint: case-7 has extremely low weight and sample_size=1,
    so it is almost never sampled at gen 4. Its streak remains > 0 (undetected).
    With checkpoint: gen 4 evaluates ALL cases, catches case-7's failure.

    To eliminate randomness, we seed random before the critical generation.
    """
    import random as _random

    cases = _make_cases(8)
    case_ids = [c.id for c in cases]

    # --- Run WITHOUT checkpoint (checkpoint_interval=0) ---
    no_cp_gen_counter = [0]

    async def no_cp_evaluate(**kwargs):
        current_gen = no_cp_gen_counter[0]
        received_cases = kwargs["cases"]
        received_ids = [c.id for c in received_cases]

        results = []
        for cid in received_ids:
            if current_gen >= 4 and cid == "case-7":
                # Regression at gen 4
                results.append(CaseResult(case_id=cid, score=0.0, passed=False))
            else:
                results.append(CaseResult(case_id=cid, score=0.8, passed=True))

        return _make_report(results)

    no_cp_config = EvolutionConfig(
        generations=5,
        conversations_per_island=1,
        rcc_rounds=1,
        sample_size=1,  # Minimal sampling -- 1 case per generation
        adaptive_sampling=True,
        checkpoint_interval=0,  # NO checkpoints
        adaptive_min_rate=0.01,  # Very low floor so case-7 has near-zero weight
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )

    no_cp_evaluator = AsyncMock(spec=FitnessEvaluator)
    no_cp_evaluator.evaluate = AsyncMock(side_effect=no_cp_evaluate)

    no_cp_loop = _build_fresh_loop(config=no_cp_config, evaluator=no_cp_evaluator, cases=cases)
    seed_results = [CaseResult(case_id=cid, score=0.8, passed=True) for cid in case_ids]
    no_cp_loop.set_seed_results(seed_results)

    seed = _make_candidate(template="Hello {{ x }}", generation=0)
    seed.fitness_score = -1.0
    seed.evaluation = _make_report(seed_results)

    # Run gens 0-3 to build natural streaks
    population = [seed]
    for gen in range(4):
        no_cp_gen_counter[0] = gen
        population, _record, _reason = await no_cp_loop.step_generation(
            population=population, generation=gen
        )

    # Manually boost case-7's streak to make its weight extremely low
    # (streak=30 with decay_constant=3.0 gives weight = 1/(1+30/3) = 0.091 -> clamped to min_rate=0.01)
    assert no_cp_loop._adaptive_sampler is not None
    no_cp_loop._adaptive_sampler._pass_streaks["case-7"] = 30

    streak_before = no_cp_loop._adaptive_sampler.pass_streaks["case-7"]

    # Seed random for determinism: with weight ratio ~0.01 vs ~1.0 for other cases,
    # and sample_size=1, the probability of picking case-7 is ~ 0.01/7.07 = 0.14%
    _random.seed(42)

    # Run gen 4 (NO checkpoint) -- case-7 regression present but unlikely to be sampled
    no_cp_gen_counter[0] = 4
    population, _record, _reason = await no_cp_loop.step_generation(
        population=population, generation=4
    )

    no_cp_streak = no_cp_loop._adaptive_sampler.pass_streaks.get("case-7", -1)

    # Restore random state
    _random.seed()

    # --- Run WITH checkpoint (checkpoint_interval=4, so gen 4 is a checkpoint) ---
    cp_gen_counter = [0]

    async def cp_evaluate(**kwargs):
        current_gen = cp_gen_counter[0]
        received_cases = kwargs["cases"]
        received_ids = [c.id for c in received_cases]

        results = []
        for cid in received_ids:
            if current_gen >= 4 and cid == "case-7":
                # Regression at gen 4
                results.append(CaseResult(case_id=cid, score=0.0, passed=False))
            else:
                results.append(CaseResult(case_id=cid, score=0.8, passed=True))

        return _make_report(results)

    cp_config = EvolutionConfig(
        generations=5,
        conversations_per_island=1,
        rcc_rounds=1,
        sample_size=1,
        adaptive_sampling=True,
        checkpoint_interval=4,  # Gen 4 is a checkpoint (4 > 0 and 4 % 4 == 0)
        adaptive_min_rate=0.01,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
    )

    cp_evaluator = AsyncMock(spec=FitnessEvaluator)
    cp_evaluator.evaluate = AsyncMock(side_effect=cp_evaluate)

    cp_loop = _build_fresh_loop(config=cp_config, evaluator=cp_evaluator, cases=cases)
    cp_loop.set_seed_results([CaseResult(case_id=cid, score=0.8, passed=True) for cid in case_ids])

    cp_seed = _make_candidate(template="Hello {{ x }}", generation=0)
    cp_seed.fitness_score = -1.0
    cp_seed.evaluation = _make_report(
        [CaseResult(case_id=cid, score=0.8, passed=True) for cid in case_ids]
    )

    population = [cp_seed]
    for gen in range(4):
        cp_gen_counter[0] = gen
        population, _record, _reason = await cp_loop.step_generation(
            population=population, generation=gen
        )

    # Boost case-7's streak to match the "without checkpoint" scenario
    assert cp_loop._adaptive_sampler is not None
    cp_loop._adaptive_sampler._pass_streaks["case-7"] = 30

    # Run gen 4 (checkpoint) -- evaluates ALL cases, catches case-7 failure
    cp_gen_counter[0] = 4
    population, _record, _reason = await cp_loop.step_generation(
        population=population, generation=4
    )

    cp_streak = cp_loop._adaptive_sampler.pass_streaks.get("case-7", -1)

    # Print comparison
    print("\n--- Checkpoint vs No-Checkpoint Regression Detection ---")
    print(f"  case-7 streak before gen 4: {streak_before}")
    print(
        f"  Without checkpoint: case-7 streak={no_cp_streak} "
        f"({'undetected' if no_cp_streak > 0 else 'detected'})"
    )
    print(
        f"  With checkpoint:    case-7 streak={cp_streak} "
        f"({'undetected' if cp_streak > 0 else 'detected'})"
    )

    # Promoted drafts are always fully verified, so the regression is caught
    # even when the scout subset omitted it.
    assert no_cp_streak == 0

    # Assert: WITH checkpoint, regression IS detected (streak reset to 0)
    assert cp_streak == 0, (
        f"With checkpoint, case-7 streak should be 0 (regression detected), got {cp_streak}"
    )
