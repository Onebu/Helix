"""Tests for BoltzmannSelector with numerically stable softmax.

Penalty-based fitness: 0.0 = perfect, negative = penalized.
All candidates participate in selection (no rejected filtering).
"""

import math
from collections import Counter

import pytest

from api.evolution.models import Candidate
from api.evolution.selector import BoltzmannSelector


@pytest.fixture
def selector():
    return BoltzmannSelector()


@pytest.fixture
def diverse_candidates():
    """Population with varied negative fitness scores (penalties)."""
    return [
        Candidate(id="low", template="low", fitness_score=-10.0),
        Candidate(id="mid", template="mid", fitness_score=-2.0),
        Candidate(id="high", template="high", fitness_score=-0.5),
    ]


class TestBoltzmannSelectorEdgeCases:
    """Edge case tests for BoltzmannSelector."""

    def test_empty_candidates_returns_empty(self, selector):
        """Empty candidate list should return empty list."""
        result = selector.select(candidates=[], n_parents=5, temperature=1.0)
        assert result == []

    def test_n_parents_zero_returns_empty(self, selector, diverse_candidates):
        """n_parents=0 should return empty list."""
        result = selector.select(candidates=diverse_candidates, n_parents=0, temperature=1.0)
        assert result == []

    def test_n_parents_negative_returns_empty(self, selector, diverse_candidates):
        """Negative n_parents should return empty list."""
        result = selector.select(candidates=diverse_candidates, n_parents=-1, temperature=1.0)
        assert result == []

    def test_all_candidates_participate_regardless_of_rejected(self, selector):
        """All candidates participate in selection, even with rejected=True."""
        candidates = [
            Candidate(template="a", fitness_score=-2.0, rejected=True),
            Candidate(template="b", fitness_score=-10.0, rejected=True),
            Candidate(template="c", fitness_score=-0.5),
        ]
        result = selector.select(candidates=candidates, n_parents=5, temperature=1.0)
        assert len(result) == 5
        # All candidates should be possible selections
        selected_templates = {c.template for c in result}
        # At least the best candidate should appear
        assert "c" in selected_templates

    def test_single_candidate_returns_n_times(self, selector):
        """Single candidate should be returned n_parents times."""
        single = Candidate(id="only", template="only one", fitness_score=-2.0)
        result = selector.select(candidates=[single], n_parents=3, temperature=1.0)
        assert len(result) == 3
        assert all(c.id == "only" for c in result)

    def test_rejected_candidates_included_in_selection(self, selector):
        """Rejected candidates participate in selection (no filtering).

        Uses a smaller score gap (-1.0 vs -2.0) and more samples (500) to
        make the test deterministic — with the old gap (-1.0 vs -5.0) and
        only 100 samples, the penalized candidate had ~1.8% per-draw
        probability, causing intermittent failures.
        """
        candidates = [
            Candidate(id="good", template="good", fitness_score=-1.0),
            Candidate(id="penalized", template="penalized", fitness_score=-2.0, rejected=True),
        ]
        result = selector.select(candidates=candidates, n_parents=500, temperature=1.0)
        assert len(result) == 500
        # Both candidates should appear at least once in 500 selections
        selected_ids = {c.id for c in result}
        assert "good" in selected_ids
        assert "penalized" in selected_ids


class TestBoltzmannSelectorDistribution:
    """Statistical tests for Boltzmann selection probability distribution."""

    def test_uniform_fitness_produces_uniform_selection(self, selector):
        """Equal fitness scores should produce roughly equal selection probability."""
        candidates = [Candidate(id=f"c{i}", template=f"t{i}", fitness_score=-2.0) for i in range(4)]
        counts = Counter()
        n_trials = 10_000
        for _ in range(n_trials):
            selected = selector.select(candidates=candidates, n_parents=1, temperature=1.0)
            counts[selected[0].id] += 1

        for cid in ["c0", "c1", "c2", "c3"]:
            proportion = counts[cid] / n_trials
            assert 0.20 < proportion < 0.30, (
                f"Candidate {cid} selected {proportion:.2%} of the time, expected ~25%"
            )

    def test_high_temperature_produces_near_uniform(self, selector, diverse_candidates):
        """High temperature (100.0) should make selection nearly uniform."""
        counts = Counter()
        n_trials = 10_000
        for _ in range(n_trials):
            selected = selector.select(
                candidates=diverse_candidates, n_parents=1, temperature=100.0
            )
            counts[selected[0].id] += 1

        for cid in ["low", "mid", "high"]:
            proportion = counts[cid] / n_trials
            assert 0.25 < proportion < 0.40, (
                f"Candidate {cid} selected {proportion:.2%}, expected near-uniform (~33%)"
            )

    def test_low_temperature_favors_least_penalized(self, selector, diverse_candidates):
        """Low temperature (0.01) should almost always select the least penalized candidate."""
        counts = Counter()
        n_trials = 1_000
        for _ in range(n_trials):
            selected = selector.select(candidates=diverse_candidates, n_parents=1, temperature=0.01)
            counts[selected[0].id] += 1

        # Least penalized (-0.5) should dominate
        high_proportion = counts["high"] / n_trials
        assert high_proportion > 0.95, (
            f"Least penalized candidate selected {high_proportion:.2%}, expected > 95%"
        )

    def test_returns_correct_number_of_parents(self, selector, diverse_candidates):
        """Should return exactly n_parents candidates."""
        for n in [1, 3, 5, 10]:
            result = selector.select(candidates=diverse_candidates, n_parents=n, temperature=1.0)
            assert len(result) == n


class TestBoltzmannSelectorNumericalStability:
    """Tests for numerical stability of the softmax computation."""

    def test_extreme_fitness_ratio_no_nan_inf(self, selector):
        """Extreme fitness ratios with low temperature should not produce nan/inf."""
        candidates = [
            Candidate(id="worst", template="worst", fitness_score=-100.0),
            Candidate(id="best", template="best", fitness_score=0.0),
        ]
        result = selector.select(candidates=candidates, n_parents=5, temperature=0.001)
        assert len(result) == 5
        for c in result:
            assert c.id in ("worst", "best")
            assert math.isfinite(c.fitness_score)

    def test_identical_fitness_no_overflow(self, selector):
        """Identical fitness values should not cause overflow."""
        candidates = [
            Candidate(id=f"c{i}", template=f"t{i}", fitness_score=-0.5) for i in range(10)
        ]
        result = selector.select(candidates=candidates, n_parents=5, temperature=0.001)
        assert len(result) == 5

    def test_very_low_temperature_selects_best(self, selector):
        """Very low temperature with fitness gap should select best (least penalized) candidate."""
        candidates = [
            Candidate(id="bad", template="bad", fitness_score=-10.0),
            Candidate(id="good", template="good", fitness_score=-0.5),
        ]
        result = selector.select(candidates=candidates, n_parents=10, temperature=0.001)
        good_count = sum(1 for c in result if c.id == "good")
        assert good_count == 10, f"Expected all 10 to be 'good', got {good_count}"
