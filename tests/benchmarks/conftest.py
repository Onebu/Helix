"""Shared fixtures for benchmark tests.

Provides mock evaluator, mock RCC engine, config factory, and test cases
with simulated I/O delays to create meaningful parallel vs sequential
timing differences.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from api.dataset.models import TestCase
from api.evaluation.evaluator import FitnessEvaluator
from api.evaluation.models import (
    CaseResult,
    EvaluationReport,
    FitnessScore,
)
from api.evolution.models import Candidate, EvolutionConfig
from api.evolution.rcc import RCCEngine


def _make_report(
    score: float,
    case_ids: list[str],
    rejected: bool = False,
) -> EvaluationReport:
    """Create an EvaluationReport with a controlled fitness score."""
    return EvaluationReport(
        fitness=FitnessScore(score=score, rejected=rejected),
        case_results=[
            CaseResult(case_id=case_id, score=score, passed=score == 0)
            for case_id in case_ids
        ],
        total_cases=len(case_ids),
        cost_summary={
            "total_calls": 1,
            "total_input_tokens": 10,
            "total_output_tokens": 10,
            "total_cost_usd": 0.001,
        },
    )


def _make_candidate(
    template: str = "evolved {{ x }}", generation: int = 0, fitness: float = -2.0
) -> Candidate:
    """Create a Candidate with a test template and fitness."""
    c = Candidate(template=template, generation=generation, parent_ids=[])
    c.fitness_score = fitness
    return c


def make_mock_evaluator(score: float = -2.0, delay: float = 0.05) -> AsyncMock:
    """Create a mock FitnessEvaluator with simulated I/O delay.

    The delay simulates LLM API latency, which is critical for measuring
    parallel speedup -- without delay, asyncio.gather has nothing to
    parallelize.

    Args:
        score: Fitness score to return (default -2.0).
        delay: Simulated I/O delay in seconds (default 50ms).

    Returns:
        AsyncMock with spec=FitnessEvaluator.
    """
    evaluator = AsyncMock(spec=FitnessEvaluator)
    call_count = 0

    async def evaluate_with_delay(*args: Any, **kwargs: Any) -> EvaluationReport:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(delay)
        cases = kwargs.get("cases")
        if cases is None and len(args) > 1:
            cases = args[1]
        return _make_report(score, [case.id for case in cases or []])

    evaluator.evaluate = AsyncMock(side_effect=evaluate_with_delay)
    return evaluator


def make_mock_rcc(delay: float = 0.02) -> AsyncMock:
    """Create a mock RCCEngine with simulated I/O delay.

    Args:
        delay: Simulated I/O delay in seconds (default 20ms).

    Returns:
        AsyncMock with spec=RCCEngine.
    """
    rcc = AsyncMock(spec=RCCEngine)
    rcc_count = 0

    async def rcc_with_delay(*args: Any, **kwargs: Any) -> list[Candidate]:
        nonlocal rcc_count
        rcc_count += 1
        await asyncio.sleep(delay)
        return [_make_candidate(template=f"evolved_{rcc_count} {{{{ x }}}}")]

    rcc.run_conversation = AsyncMock(side_effect=rcc_with_delay)
    return rcc


@pytest.fixture
def mock_evaluator() -> AsyncMock:
    """Mock FitnessEvaluator with 50ms simulated I/O delay."""
    return make_mock_evaluator()


@pytest.fixture
def mock_rcc() -> AsyncMock:
    """Mock RCCEngine with 20ms simulated I/O delay."""
    return make_mock_rcc()


@pytest.fixture
def benchmark_config_factory():
    """Factory for creating EvolutionConfig with benchmark-friendly defaults.

    Returns a callable that creates EvolutionConfig with sensible defaults
    for benchmarking, accepting keyword overrides.
    """

    def _factory(**overrides: Any) -> EvolutionConfig:
        defaults = {
            "generations": 2,
            "conversations_per_island": 2,
            "n_seq": 1,
            "n_islands": 3,
            "n_emigrate": 0,
            "reset_interval": 0,
            "n_seed_variants": 0,
            "structural_mutation_probability": 0.0,
            "pr_no_parents": 0.0,
            "population_cap": 10,
        }
        defaults.update(overrides)
        return EvolutionConfig(**defaults)

    return _factory


@pytest.fixture
def benchmark_cases() -> list[TestCase]:
    """Three simple TestCase objects with chat_history for benchmarks."""
    return [
        TestCase(chat_history=[{"role": "user", "content": "hello"}]),
        TestCase(chat_history=[{"role": "user", "content": "help me"}]),
        TestCase(chat_history=[{"role": "user", "content": "goodbye"}]),
    ]
