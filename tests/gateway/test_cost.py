"""Tests for CostTracker and estimate_cost_from_tokens.

COST-01: System tracks total LLM API calls, input tokens, output tokens,
and estimated dollar cost per evolution run.
"""

import math
from datetime import UTC, datetime

import pytest

from api.types import LLMResponse, ModelRole


def _make_response(
    role: ModelRole = ModelRole.META,
    input_tokens: int = 100,
    output_tokens: int = 50,
    cost_usd: float = 0.01,
    model: str = "anthropic/claude-sonnet-4",
) -> LLMResponse:
    """Helper to create test LLMResponse objects."""
    return LLMResponse(
        content="test response",
        model_used=model,
        role=role,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        timestamp=datetime.now(UTC),
    )


class TestEstimateCostFromTokens:
    """Test static pricing table cost estimation."""

    def test_known_model_returns_cost(self):
        """COST-01: estimate_cost_from_tokens returns correct cost for known models."""
        from api.gateway.cost import estimate_cost_from_tokens

        cost = estimate_cost_from_tokens("openai/gpt-4o-mini", 1000, 500)
        assert cost is not None
        assert cost > 0

    def test_claude_sonnet_returns_cost(self):
        """COST-01: Pricing for claude-sonnet-4."""
        from api.gateway.cost import estimate_cost_from_tokens

        cost = estimate_cost_from_tokens("anthropic/claude-sonnet-4", 1000, 500)
        assert cost is not None
        assert cost > 0

    def test_unknown_model_returns_none(self):
        """COST-01: estimate_cost_from_tokens returns None for unknown models."""
        from api.gateway.cost import estimate_cost_from_tokens

        cost = estimate_cost_from_tokens("some-vendor/unknown-model-xyz", 1000, 500)
        assert cost is None

    def test_cost_calculation_accuracy(self):
        """COST-01: Cost = (input * input_rate / 1M) + (output * output_rate / 1M)."""
        from api.gateway.cost import MODEL_PRICING, estimate_cost_from_tokens

        # Pick a model from the pricing table and verify calculation
        model = "openai/gpt-4o-mini"
        pricing = MODEL_PRICING[model]
        input_tokens = 1_000_000
        output_tokens = 1_000_000

        cost = estimate_cost_from_tokens(model, input_tokens, output_tokens)
        expected = pricing["input_per_million"] + pricing["output_per_million"]
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_pricing_table_has_minimum_models(self):
        """COST-01: Static pricing table has at least 8 models."""
        from api.gateway.cost import MODEL_PRICING

        assert len(MODEL_PRICING) >= 8

    @pytest.mark.parametrize(
        ("alias", "canonical"),
        [
            ("gpt-4o-mini", "openai/gpt-4o-mini"),
            ("google/gemini-2.5-flash", "gemini-2.5-flash"),
            ("gemini-2.0-flash-001", "google/gemini-2.0-flash-001"),
        ],
    )
    def test_common_provider_aliases_have_pricing_parity(self, alias, canonical):
        from api.gateway.cost import estimate_cost_from_tokens

        assert estimate_cost_from_tokens(alias, 1000, 500) == estimate_cost_from_tokens(
            canonical, 1000, 500
        )


class TestGeminiDirectPricing:
    """GEM-03: Static pricing table includes Gemini direct API models."""

    def test_gemini_flash_pricing(self):
        """estimate_cost_from_tokens('gemini-2.5-flash', 1000, 500) returns correct cost."""
        from api.gateway.cost import estimate_cost_from_tokens

        cost = estimate_cost_from_tokens("gemini-2.5-flash", 1000, 500)
        assert cost is not None
        # gemini-2.5-flash: $0.15/M input, $0.60/M output
        expected = (1000 * 0.15 / 1_000_000) + (500 * 0.60 / 1_000_000)
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_gemini_pro_pricing(self):
        """estimate_cost_from_tokens('gemini-2.5-pro', 1000, 500) returns correct cost."""
        from api.gateway.cost import estimate_cost_from_tokens

        cost = estimate_cost_from_tokens("gemini-2.5-pro", 1000, 500)
        assert cost is not None
        # gemini-2.5-pro: $1.25/M input, $10.0/M output
        expected = (1000 * 1.25 / 1_000_000) + (500 * 10.0 / 1_000_000)
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_gemini_flash_lite_pricing(self):
        """estimate_cost_from_tokens('gemini-2.0-flash-lite', 1000, 500) returns correct cost."""
        from api.gateway.cost import estimate_cost_from_tokens

        cost = estimate_cost_from_tokens("gemini-2.0-flash-lite", 1000, 500)
        assert cost is not None
        # gemini-2.0-flash-lite: $0.0/M input, $0.0/M output (free tier)
        assert cost == pytest.approx(0.0)


class TestCostTracker:
    """Test CostTracker aggregation."""

    def test_record_stores_response(self):
        """COST-01: CostTracker.record stores per-call data."""
        from api.gateway.cost import CostTracker

        tracker = CostTracker()
        response = _make_response()
        tracker.record(response)
        assert len(tracker._records) == 1

    def test_summary_aggregates_totals(self):
        """COST-01: CostTracker.summary() returns aggregate totals."""
        from api.gateway.cost import CostTracker

        tracker = CostTracker()
        tracker.record(_make_response(input_tokens=100, output_tokens=50, cost_usd=0.01))
        tracker.record(_make_response(input_tokens=200, output_tokens=100, cost_usd=0.02))

        summary = tracker.summary()
        assert summary["total_calls"] == 2
        assert summary["total_input_tokens"] == 300
        assert summary["total_output_tokens"] == 150
        assert summary["total_cost_usd"] == pytest.approx(0.03)

    def test_summary_empty_tracker(self):
        """COST-01: summary() with no records returns zeros."""
        from api.gateway.cost import CostTracker

        tracker = CostTracker()
        summary = tracker.summary()
        assert summary["total_calls"] == 0
        assert summary["total_input_tokens"] == 0
        assert summary["total_output_tokens"] == 0
        assert summary["total_cost_usd"] == 0.0

    def test_by_role_breakdown(self):
        """COST-01: CostTracker.by_role() breaks down costs by ModelRole."""
        from api.gateway.cost import CostTracker

        tracker = CostTracker()
        tracker.record(_make_response(role=ModelRole.META, cost_usd=0.10))
        tracker.record(_make_response(role=ModelRole.META, cost_usd=0.05))
        tracker.record(_make_response(role=ModelRole.TARGET, cost_usd=0.02))
        tracker.record(_make_response(role=ModelRole.JUDGE, cost_usd=0.03))

        by_role = tracker.by_role()
        assert ModelRole.META in by_role
        assert ModelRole.TARGET in by_role
        assert ModelRole.JUDGE in by_role
        assert by_role[ModelRole.META]["total_calls"] == 2
        assert by_role[ModelRole.META]["total_cost_usd"] == pytest.approx(0.15)
        assert by_role[ModelRole.TARGET]["total_calls"] == 1
        assert by_role[ModelRole.JUDGE]["total_calls"] == 1

    def test_reset_clears_records(self):
        """COST-01: CostTracker.reset() clears all records."""
        from api.gateway.cost import CostTracker

        tracker = CostTracker()
        tracker.record(_make_response())
        tracker.record(_make_response())
        assert tracker.summary()["total_calls"] == 2

        tracker.reset()
        assert tracker.summary()["total_calls"] == 0

    def test_cost_tracker_summary_snapshot_safety(self):
        """EVO-01: summary() uses snapshot copy for safe concurrent reads.

        Verifies that summary() returns consistent totals when 100 records
        are present -- a baseline correctness test ensuring snapshot iteration.
        """
        from api.gateway.cost import CostTracker

        tracker = CostTracker()
        for _i in range(100):
            tracker.record(_make_response(input_tokens=10, output_tokens=5, cost_usd=0.001))

        summary = tracker.summary()
        assert summary["total_calls"] == 100
        assert summary["total_input_tokens"] == 1000
        assert summary["total_output_tokens"] == 500
        assert summary["total_cost_usd"] == pytest.approx(0.1)

        # Verify by_role also works consistently with many records
        by_role = tracker.by_role()
        meta_totals = by_role[ModelRole.META]
        assert meta_totals["total_calls"] == 100
        assert meta_totals["total_input_tokens"] == 1000

    def test_budgeted_run_rejects_unknown_model(self):
        from api.exceptions import ConfigError
        from api.gateway.cost import CostTracker

        with pytest.raises(ConfigError, match="pricing unavailable"):
            CostTracker(budget_cap_usd=1).validate_models(["vendor/unknown"])

    def test_unbudgeted_run_allows_unknown_model(self):
        from api.gateway.cost import CostTracker

        CostTracker().validate_models(["vendor/unknown"])

    @pytest.mark.parametrize("cap", [-0.01, math.nan, math.inf, -math.inf, True, "1"])
    def test_budget_cap_must_be_finite_nonnegative_number(self, cap):
        from api.gateway.cost import CostTracker

        with pytest.raises(ValueError, match="budget_cap_usd"):
            CostTracker(budget_cap_usd=cap)

    def test_budgeted_validation_accepts_priced_alias(self):
        from api.gateway.cost import CostTracker

        CostTracker(budget_cap_usd=1).validate_models(["gpt-4o-mini"])

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("input_tokens", "output_tokens"),
        [(0, 1), (-1, 1), (True, 1), (1.5, 1), (1, 0), (1, False), (1, math.nan)],
    )
    async def test_reserve_requires_positive_integer_token_counts(
        self, input_tokens, output_tokens
    ):
        from api.gateway.cost import CostTracker

        with pytest.raises(ValueError, match="tokens"):
            await CostTracker(budget_cap_usd=1).reserve(
                "openai/gpt-4o-mini", input_tokens, output_tokens
            )

    @pytest.mark.asyncio
    async def test_reconcile_releases_reservation_before_rejecting_bad_response(self):
        from api.gateway.cost import CostTracker

        tracker = CostTracker(budget_cap_usd=1)
        reservation = await tracker.reserve("openai/gpt-4o-mini", 10, 10)
        invalid = _make_response().model_copy(update={"cost_usd": math.nan})

        with pytest.raises(ValueError, match="cost_usd"):
            await tracker.reconcile(reservation, invalid)

        assert tracker._reserved_usd == 0
        assert tracker.summary()["total_calls"] == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("reservation", [-1, math.nan, math.inf, True, "0"])
    async def test_reconcile_rejects_invalid_reservation(self, reservation):
        from api.gateway.cost import CostTracker

        with pytest.raises(ValueError, match="reservation"):
            await CostTracker().reconcile(reservation, None)

    @pytest.mark.asyncio
    async def test_reconcile_cannot_release_more_than_reserved(self):
        from api.gateway.cost import CostTracker

        tracker = CostTracker()
        await tracker.reserve("vendor/unknown", 1, 1)
        with pytest.raises(ValueError, match="exceeds"):
            await tracker.reconcile(0.01, None)
        await tracker.reconcile(0, None)

    @pytest.mark.asyncio
    async def test_reset_rejects_active_reservation(self):
        from api.gateway.cost import CostTracker

        tracker = CostTracker()
        reservation = await tracker.reserve("openai/gpt-4o-mini", 10, 10)
        with pytest.raises(RuntimeError, match="active reservations"):
            tracker.reset()
        await tracker.reconcile(reservation, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("model", ["gemini-2.0-flash-lite", "vendor/unknown"])
    async def test_zero_cost_reservation_blocks_reset_until_reconciled(self, model):
        from api.gateway.cost import CostTracker

        tracker = CostTracker()
        reservation = await tracker.reserve(model, 10, 10)
        assert reservation == 0
        assert tracker._active_reservations == 1
        with pytest.raises(RuntimeError, match="active reservations"):
            tracker.reset()

        await tracker.reconcile(reservation, None)
        assert tracker._active_reservations == 0
        tracker.reset()

    @pytest.mark.asyncio
    async def test_multiple_reservations_reconcile_to_exact_zero(self):
        from api.gateway.cost import CostTracker

        tracker = CostTracker()
        reservations = [
            await tracker.reserve("openai/gpt-4o-mini", 11, 13),
            await tracker.reserve("openai/gpt-4o-mini", 17, 19),
            await tracker.reserve("vendor/unknown", 1, 1),
        ]
        for reservation in reservations:
            await tracker.reconcile(reservation, None)

        assert tracker._reserved_usd == 0
        assert tracker._active_reservations == 0
        tracker.reset()

    @pytest.mark.asyncio
    async def test_reconcile_requires_an_active_reservation(self):
        from api.gateway.cost import CostTracker

        with pytest.raises(ValueError, match="no active reservation"):
            await CostTracker().reconcile(0, None)
