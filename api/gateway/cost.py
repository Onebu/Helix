"""Cost tracking and estimation for LLM API calls.

Provides a static pricing table for common OpenRouter and Gemini direct API models,
token-based cost estimation, and an in-memory cost aggregator.
"""

import asyncio
import logging
import math
from collections import defaultdict

from api.exceptions import BudgetExhaustedError, ConfigError
from api.types import LLMResponse, ModelRole

logger = logging.getLogger(__name__)

# Static pricing table for common OpenRouter and Gemini direct API models.
# Prices in USD per million tokens.
# Source: OpenRouter pricing pages, Google AI Studio (approximate, updated periodically).
MODEL_PRICING: dict[str, dict[str, float]] = {
    "anthropic/claude-sonnet-4": {
        "input_per_million": 3.0,
        "output_per_million": 15.0,
    },
    "anthropic/claude-haiku-3.5": {
        "input_per_million": 0.80,
        "output_per_million": 4.0,
    },
    "anthropic/claude-opus-4": {
        "input_per_million": 15.0,
        "output_per_million": 75.0,
    },
    "openai/gpt-4o": {
        "input_per_million": 2.50,
        "output_per_million": 10.0,
    },
    "openai/gpt-4o-mini": {
        "input_per_million": 0.15,
        "output_per_million": 0.60,
    },
    "openai/gpt-4.1": {
        "input_per_million": 2.0,
        "output_per_million": 8.0,
    },
    "openai/gpt-4.1-mini": {
        "input_per_million": 0.40,
        "output_per_million": 1.60,
    },
    "google/gemini-2.0-flash-001": {
        "input_per_million": 0.10,
        "output_per_million": 0.40,
    },
    "google/gemini-2.5-pro-preview": {
        "input_per_million": 1.25,
        "output_per_million": 10.0,
    },
    "meta-llama/llama-3.3-70b-instruct": {
        "input_per_million": 0.30,
        "output_per_million": 0.30,
    },
    # Gemini direct API models (different name format from OpenRouter)
    "gemini-2.5-pro": {
        "input_per_million": 1.25,
        "output_per_million": 10.0,
    },
    "gemini-2.5-flash": {
        "input_per_million": 0.15,
        "output_per_million": 0.60,
    },
    "gemini-2.0-flash-lite": {
        "input_per_million": 0.0,
        "output_per_million": 0.0,
    },
    "gemini-3-flash-preview": {
        "input_per_million": 0.15,
        "output_per_million": 0.60,
    },
}


def resolve_pricing_model(model: str) -> str | None:
    """Return the existing pricing key for a supported provider-name alias."""
    if not isinstance(model, str):
        return None
    if model in MODEL_PRICING:
        return model

    candidates: list[str] = []
    for provider in ("openai", "google"):
        prefix = f"{provider}/"
        if model.startswith(prefix):
            candidates.append(model[len(prefix):])
        else:
            candidates.append(f"{prefix}{model}")
    return next((candidate for candidate in candidates if candidate in MODEL_PRICING), None)


def estimate_cost_from_tokens(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimate cost from token counts using static pricing table.

    Args:
        model: OpenRouter model identifier (e.g., "openai/gpt-4o-mini").
        input_tokens: Number of input/prompt tokens.
        output_tokens: Number of output/completion tokens.

    Returns:
        Estimated cost in USD, or None if model is not in pricing table.
    """
    pricing_model = resolve_pricing_model(model)
    if pricing_model is None:
        return None
    pricing = MODEL_PRICING[pricing_model]

    cost = (input_tokens * pricing["input_per_million"] / 1_000_000) + (
        output_tokens * pricing["output_per_million"] / 1_000_000
    )
    return cost


class CostTracker:
    """In-memory aggregator for LLM call costs.

    Records individual LLMResponse objects and provides
    summary aggregation by total and by role.
    Persistence to DB happens separately when the evolution run completes.
    """

    def __init__(self, budget_cap_usd: float | None = None):
        if budget_cap_usd is not None and (
            isinstance(budget_cap_usd, bool)
            or not isinstance(budget_cap_usd, (int, float))
            or not math.isfinite(budget_cap_usd)
            or budget_cap_usd < 0
        ):
            raise ValueError("budget_cap_usd must be a finite nonnegative number")
        self._records: list[LLMResponse] = []
        self.budget_cap_usd = budget_cap_usd
        self._reserved_usd = 0.0
        self._active_reservations = 0
        self._lock = asyncio.Lock()

    def validate_models(self, models: list[str]) -> None:
        """Reject unpriced models only when calls must obey a budget cap."""
        if self.budget_cap_usd is None:
            return
        for model in models:
            if resolve_pricing_model(model) is None:
                raise ConfigError(f"Model pricing unavailable for budgeted run: {model}")

    async def reserve(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Atomically reserve the estimated cost of an upcoming call."""
        self._validate_positive_tokens(input_tokens, "input_tokens")
        self._validate_positive_tokens(output_tokens, "output_tokens")
        estimate = estimate_cost_from_tokens(model, input_tokens, output_tokens)
        if estimate is None:
            if self.budget_cap_usd is not None:
                raise ConfigError(f"Model pricing unavailable for budgeted run: {model}")
            estimate = 0.0

        async with self._lock:
            spent = self.summary()["total_cost_usd"]
            if (
                self.budget_cap_usd is not None
                and spent + self._reserved_usd + estimate > self.budget_cap_usd
            ):
                raise BudgetExhaustedError(
                    "Budget cap would be exceeded by the next LLM call"
                )
            self._reserved_usd += estimate
            self._active_reservations += 1
        return estimate

    async def reconcile(self, reservation: float, response: LLMResponse | None) -> None:
        """Release a reservation and record one successful response."""
        if (
            isinstance(reservation, bool)
            or not isinstance(reservation, (int, float))
            or not math.isfinite(reservation)
            or reservation < 0
        ):
            raise ValueError("reservation must be a finite nonnegative number")
        async with self._lock:
            if self._active_reservations == 0:
                raise ValueError("reconcile called with no active reservation")
            if reservation > self._reserved_usd and not math.isclose(
                reservation, self._reserved_usd, abs_tol=1e-12
            ):
                raise ValueError("reservation exceeds currently reserved total")
            self._reserved_usd = max(0.0, self._reserved_usd - reservation)
            if self._reserved_usd < 1e-12:
                self._reserved_usd = 0.0
            self._active_reservations -= 1
            if response is not None:
                self._validate_response(response)
                self._records.append(response)

    def record(self, response: LLMResponse) -> None:
        """Record a single LLM call response."""
        self._validate_response(response)
        self._records.append(response)

    def summary(self) -> dict:
        """Aggregate totals across all recorded calls.

        Uses a snapshot copy of _records to avoid inconsistent reads when
        concurrent asyncio tasks append to _records during iteration.

        Returns:
            Dict with total_calls, total_input_tokens, total_output_tokens, total_cost_usd.
        """
        records = list(self._records)
        return {
            "total_calls": len(records),
            "total_input_tokens": sum(r.input_tokens for r in records),
            "total_output_tokens": sum(r.output_tokens for r in records),
            "total_cost_usd": sum(r.cost_usd for r in records),
        }

    def by_role(self) -> dict[ModelRole, dict]:
        """Break down costs by ModelRole (meta/target/judge).

        Uses a snapshot copy of _records to avoid inconsistent reads when
        concurrent asyncio tasks append to _records during iteration.

        Returns:
            Dict mapping ModelRole to summary dict (same structure as summary()).
        """
        records = list(self._records)
        grouped: dict[ModelRole, list[LLMResponse]] = defaultdict(list)
        for r in records:
            grouped[r.role].append(r)

        result = {}
        for role, records in grouped.items():
            result[role] = {
                "total_calls": len(records),
                "total_input_tokens": sum(r.input_tokens for r in records),
                "total_output_tokens": sum(r.output_tokens for r in records),
                "total_cost_usd": sum(r.cost_usd for r in records),
            }
        return result

    def reset(self) -> None:
        """Clear all recorded data."""
        if self._active_reservations > 0:
            raise RuntimeError("Cannot reset CostTracker with active reservations")
        self._records.clear()

    @staticmethod
    def _validate_positive_tokens(value: int, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} tokens must be a positive integer")

    @staticmethod
    def _validate_response(response: LLMResponse) -> None:
        for name in ("input_tokens", "output_tokens"):
            value = getattr(response, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"response {name} must be a nonnegative integer")
        cost = response.cost_usd
        if (
            isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(cost)
            or cost < 0
        ):
            raise ValueError("response cost_usd must be a finite nonnegative number")
