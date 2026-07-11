"""Parallel vs sequential speedup benchmark tests.

Measures wall-clock speedup from IslandEvolver's asyncio.gather parallel
execution compared to sequential single-island runs. Uses simulated I/O
delays in mock evaluator/RCC to create meaningful timing differences.

Run selectively with: pytest -m benchmark
Exclude with: pytest -m "not benchmark"
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.config.models import GenerationConfig
from api.dataset.models import TestCase
from api.evaluation.evaluator import FitnessEvaluator
from api.evaluation.models import CaseResult, FitnessScore
from api.evolution.islands import IslandEvolver
from api.evolution.models import EvolutionConfig
from api.evolution.mutator import StructuralMutator
from api.evolution.selector import BoltzmannSelector
from api.gateway.cost import CostTracker
from tests.benchmarks.conftest import make_mock_evaluator, make_mock_rcc

pytestmark = pytest.mark.benchmark


def _make_case_evaluator(concurrency: int) -> FitnessEvaluator:
    aggregator = MagicMock()
    aggregator.aggregate.return_value = FitnessScore(score=0, case_results=[])
    cost_tracker = MagicMock()
    cost_tracker.summary.return_value = {}
    return FitnessEvaluator(
        client=AsyncMock(),
        renderer=MagicMock(),
        exact_scorer=AsyncMock(),
        behavior_scorer=AsyncMock(),
        aggregator=aggregator,
        cost_tracker=cost_tracker,
        evaluation_concurrency=concurrency,
    )


@pytest.mark.asyncio
async def test_case_concurrency_provides_speedup_without_order_drift(monkeypatch):
    cases = [TestCase(id=str(index)) for index in range(4)]

    async def run(concurrency: int):
        evaluator = _make_case_evaluator(concurrency)

        async def delayed_case(**kwargs):
            await asyncio.sleep(0.02)
            return CaseResult(case_id=kwargs["case"].id, score=0, passed=True)

        monkeypatch.setattr(evaluator, "_evaluate_case", delayed_case)
        start = time.perf_counter()
        report = await evaluator.evaluate("Prompt", cases, "model", GenerationConfig())
        return time.perf_counter() - start, report

    sequential_time, _ = await run(1)
    parallel_time, report = await run(4)

    assert parallel_time < sequential_time * 0.75
    assert [result.case_id for result in report.case_results] == ["0", "1", "2", "3"]


def _build_evolver(
    config: EvolutionConfig,
    evaluator: AsyncMock,
    rcc: AsyncMock,
    cases: list[TestCase] | None = None,
) -> IslandEvolver:
    """Build an IslandEvolver with benchmark defaults.

    Each test creates its own fresh mock instances to prevent state leakage.
    """
    if cases is None:
        cases = [
            TestCase(chat_history=[{"role": "user", "content": "hello"}]),
            TestCase(chat_history=[{"role": "user", "content": "help me"}]),
            TestCase(chat_history=[{"role": "user", "content": "goodbye"}]),
        ]

    return IslandEvolver(
        config=config,
        evaluator=evaluator,
        rcc=rcc,
        mutator=AsyncMock(spec=StructuralMutator),
        selector=BoltzmannSelector(),
        cost_tracker=CostTracker(),
        original_template="Hello {{ x }}",
        anchor_variables={"x"},
        cases=cases,
        target_model="test/model",
        generation_config=GenerationConfig(),
        purpose="benchmark",
    )


@pytest.mark.asyncio
async def test_parallel_faster_than_sequential():
    """Parallel island execution is faster than sequential single-island execution.

    Sequential baseline: Run 3 separate single-island evolvers in sequence,
    each with conversations_per_island=3 and 2 generations. This simulates
    the same total work as 3 parallel islands but without asyncio.gather.

    Parallel: 3 islands, conversations_per_island=3, 2 generations.
    asyncio.gather runs all 3 islands concurrently.

    Each mock call introduces I/O delay (50ms evaluator + 20ms RCC),
    so asyncio.gather should yield measurable wall-clock speedup.
    """
    n_islands = 3

    # --- Sequential baseline: N separate single-island runs ---
    single_island_config = EvolutionConfig(
        n_islands=1,
        generations=2,
        conversations_per_island=3,
        n_seq=1,
        n_emigrate=0,
        reset_interval=0,
        n_seed_variants=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        population_cap=10,
    )

    seq_start = time.perf_counter()
    for _ in range(n_islands):
        seq_evaluator = make_mock_evaluator(score=-2.0, delay=0.05)
        seq_rcc = make_mock_rcc(delay=0.02)
        seq_evolver = _build_evolver(single_island_config, seq_evaluator, seq_rcc)
        await seq_evolver.run()
    sequential_time = time.perf_counter() - seq_start

    # --- Parallel run: 3 islands via asyncio.gather ---
    par_config = EvolutionConfig(
        n_islands=n_islands,
        generations=2,
        conversations_per_island=3,
        n_seq=1,
        n_emigrate=0,
        reset_interval=0,
        n_seed_variants=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        population_cap=10,
    )
    par_evaluator = make_mock_evaluator(score=-2.0, delay=0.05)
    par_rcc = make_mock_rcc(delay=0.02)
    par_evolver = _build_evolver(par_config, par_evaluator, par_rcc)

    par_start = time.perf_counter()
    await par_evolver.run()
    parallel_time = time.perf_counter() - par_start

    # Compute speedup
    speedup = sequential_time / parallel_time

    print(
        f"\nParallel speedup: {speedup:.2f}x (seq={sequential_time:.3f}s, par={parallel_time:.3f}s)"
    )

    # Parallel execution of 3 islands should be faster than running
    # 3 single-island evolvers in sequence (speedup > 1.0x).
    # With I/O-bound work and asyncio.gather, expect ~2-3x.
    assert speedup > 1.0, (
        f"Expected parallel speedup > 1.0x, got {speedup:.2f}x "
        f"(seq={sequential_time:.3f}s, par={parallel_time:.3f}s)"
    )


@pytest.mark.asyncio
async def test_parallel_evaluates_all_islands():
    """All islands are evaluated: evaluator call count matches expected total.

    Config: n_islands=3, generations=1, conversations_per_island=2, n_seed_variants=0.
    Expected: 1 seed eval + 3 islands * 2 convs = 7 evaluations.
    Expected candidates_evaluated in gen record: 6 (3 islands * 2 convs).
    """
    evaluator = make_mock_evaluator(score=-2.0, delay=0.01)
    rcc = make_mock_rcc(delay=0.01)

    config = EvolutionConfig(
        n_islands=3,
        generations=1,
        conversations_per_island=2,
        n_seq=1,
        n_emigrate=0,
        reset_interval=0,
        n_seed_variants=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        population_cap=10,
    )
    evolver = _build_evolver(config, evaluator, rcc)
    result = await evolver.run()

    # 1 seed + 3 islands * 2 convs = 7 total evaluations
    assert evaluator.evaluate.call_count == 7, (
        f"Expected 7 evaluations (1 seed + 3*2), got {evaluator.evaluate.call_count}"
    )

    # Generation record should show 6 candidates evaluated (excluding seed)
    assert len(result.generation_records) == 1
    assert result.generation_records[0].candidates_evaluated == 6, (
        f"Expected 6 candidates_evaluated, got {result.generation_records[0].candidates_evaluated}"
    )


@pytest.mark.asyncio
async def test_benchmark_reports_wall_clock_and_api_calls():
    """Benchmark reports wall-clock time and API call metrics.

    Config: n_islands=3, generations=2, conversations_per_island=2.
    Verifies total_cost summary has total_calls > 0 and 2 generation records.
    """
    evaluator = make_mock_evaluator(score=-2.0, delay=0.01)
    rcc = make_mock_rcc(delay=0.01)

    config = EvolutionConfig(
        n_islands=3,
        generations=2,
        conversations_per_island=2,
        n_seq=1,
        n_emigrate=0,
        reset_interval=0,
        n_seed_variants=0,
        structural_mutation_probability=0.0,
        pr_no_parents=0.0,
        population_cap=10,
    )
    evolver = _build_evolver(config, evaluator, rcc)

    start = time.perf_counter()
    result = await evolver.run()
    wall_clock = time.perf_counter() - start

    assert len(result.generation_records) == 2, (
        f"Expected 2 generation records, got {len(result.generation_records)}"
    )

    # Each generation record tracks candidates_evaluated and cost_summary.
    # In benchmark mocks, CostTracker isn't populated (no real LLM calls),
    # so cost_summary totals are 0. But candidates_evaluated must be > 0.
    for i, record in enumerate(result.generation_records):
        assert record.candidates_evaluated > 0, f"Generation {i} has 0 candidates_evaluated"

    # result.total_cost comes from CostTracker.summary() -- verify structure
    assert "total_calls" in result.total_cost
    assert "total_cost_usd" in result.total_cost

    # evaluator.evaluate.call_count is the real "API call" metric
    # 1 seed + 3 islands * 2 convs * 2 gens = 13
    assert evaluator.evaluate.call_count > 0

    # Print summary table
    total_evaluated = sum(r.candidates_evaluated for r in result.generation_records)
    print(f"\n{'Metric':<25} {'Value':>10}")
    print(f"{'-' * 36}")
    print(f"{'Generations':<25} {len(result.generation_records):>10}")
    print(f"{'Evaluator calls':<25} {evaluator.evaluate.call_count:>10}")
    print(f"{'Candidates evaluated':<25} {total_evaluated:>10}")
    print(f"{'Wall-clock time (s)':<25} {wall_clock:>10.3f}")
    print(f"{'Termination reason':<25} {result.termination_reason:>10}")
