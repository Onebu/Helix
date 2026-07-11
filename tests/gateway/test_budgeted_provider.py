"""Tests for pre-call budget reservation and provider-owned accounting."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from api.exceptions import BudgetExhaustedError, ConfigError
from api.gateway.budgeted_provider import BudgetedProvider
from api.gateway.cost import CostTracker
from api.types import LLMResponse, ModelRole


def _response(*, cost_usd: float = 0.002, model: str = "openai/gpt-4o-mini") -> LLMResponse:
    return LLMResponse(
        content="ok",
        model_used=model,
        role=ModelRole.TARGET,
        input_tokens=100,
        output_tokens=50,
        cost_usd=cost_usd,
        timestamp=datetime.now(UTC),
    )


def _request(model: str = "openai/gpt-4o-mini") -> dict:
    # Estimated cost is about $0.00255: one call fits a $0.004 cap, two do not.
    return {
        "messages": [{"role": "user", "content": "x" * 4000}],
        "model": model,
        "role": ModelRole.TARGET,
        "max_tokens": 4000,
    }


@pytest.mark.asyncio
async def test_second_reservation_is_rejected_before_remote_call():
    inner = AsyncMock()
    inner.chat_completion.return_value = _response()
    tracker = CostTracker(budget_cap_usd=0.004)
    provider = BudgetedProvider(inner, tracker)

    await provider.chat_completion(**_request())
    with pytest.raises(BudgetExhaustedError):
        await provider.chat_completion(**_request())

    assert inner.chat_completion.await_count == 1


@pytest.mark.asyncio
async def test_concurrent_reservations_cannot_oversubscribe_budget():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_completion(**_kwargs):
        entered.set()
        await release.wait()
        return _response()

    inner = AsyncMock()
    inner.chat_completion.side_effect = blocked_completion
    provider = BudgetedProvider(inner, CostTracker(budget_cap_usd=0.004))

    first = asyncio.create_task(provider.chat_completion(**_request()))
    await entered.wait()
    try:
        with pytest.raises(BudgetExhaustedError):
            await provider.chat_completion(**_request())
    finally:
        release.set()
    await first

    assert inner.chat_completion.await_count == 1


@pytest.mark.asyncio
async def test_provider_exception_releases_reservation():
    inner = AsyncMock()
    inner.chat_completion.side_effect = [RuntimeError("remote failed"), _response()]
    tracker = CostTracker(budget_cap_usd=0.004)
    provider = BudgetedProvider(inner, tracker)

    with pytest.raises(RuntimeError, match="remote failed"):
        await provider.chat_completion(**_request())
    response = await provider.chat_completion(**_request())

    assert response.content == "ok"
    assert tracker.summary()["total_calls"] == 1
    assert inner.chat_completion.await_count == 2


@pytest.mark.asyncio
async def test_actual_response_is_recorded_exactly_once():
    inner = AsyncMock()
    inner.chat_completion.return_value = _response(cost_usd=0.0017)
    tracker = CostTracker(budget_cap_usd=0.01)
    provider = BudgetedProvider(inner, tracker)

    await provider.chat_completion(**_request())

    assert tracker.summary() == {
        "total_calls": 1,
        "total_input_tokens": 100,
        "total_output_tokens": 50,
        "total_cost_usd": pytest.approx(0.0017),
    }


@pytest.mark.asyncio
async def test_budgeted_unknown_model_is_rejected_before_remote_call():
    inner = AsyncMock()
    provider = BudgetedProvider(inner, CostTracker(budget_cap_usd=1))

    with pytest.raises(ConfigError, match="pricing unavailable"):
        await provider.chat_completion(**_request("vendor/unknown"))

    inner.chat_completion.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["max_tokens", "max_completion_tokens"])
@pytest.mark.parametrize("value", [0, -1, 1.5, True, "10"])
async def test_explicit_output_token_limit_must_be_positive_integer(field, value):
    inner = AsyncMock()
    provider = BudgetedProvider(inner, CostTracker())
    request = _request()
    request.pop("max_tokens")
    request[field] = value

    with pytest.raises(ValueError, match=field):
        await provider.chat_completion(**request)
    inner.chat_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_does_not_leak_reservation():
    entered = asyncio.Event()

    async def blocked_completion(**_kwargs):
        entered.set()
        await asyncio.Event().wait()

    inner = AsyncMock()
    inner.chat_completion.side_effect = blocked_completion
    tracker = CostTracker(budget_cap_usd=0.004)
    provider = BudgetedProvider(inner, tracker)
    task = asyncio.create_task(provider.chat_completion(**_request()))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert tracker._reserved_usd == 0
    inner.chat_completion.side_effect = None
    inner.chat_completion.return_value = _response()
    await provider.chat_completion(**_request())
    assert tracker.summary()["total_calls"] == 1


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_cancel_reconciliation():
    entered = asyncio.Event()
    cleanup_started = asyncio.Event()
    finish_cleanup = asyncio.Event()

    async def blocked_completion(**_kwargs):
        entered.set()
        await asyncio.Event().wait()

    inner = AsyncMock()
    inner.chat_completion.side_effect = blocked_completion
    tracker = CostTracker(budget_cap_usd=0.004)
    original_reconcile = tracker.reconcile

    async def blocked_reconcile(reservation, response):
        cleanup_started.set()
        await finish_cleanup.wait()
        await original_reconcile(reservation, response)

    tracker.reconcile = blocked_reconcile
    provider = BudgetedProvider(inner, tracker)
    task = asyncio.create_task(provider.chat_completion(**_request()))
    await entered.wait()
    task.cancel()
    await cleanup_started.wait()
    task.cancel()
    finish_cleanup.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert tracker._active_reservations == 0
    assert tracker._reserved_usd == 0


@pytest.mark.asyncio
async def test_invalid_response_accounting_releases_without_recording():
    inner = AsyncMock()
    inner.chat_completion.return_value = _response().model_copy(update={"input_tokens": -1})
    tracker = CostTracker(budget_cap_usd=0.004)
    provider = BudgetedProvider(inner, tracker)

    with pytest.raises(ValueError, match="input_tokens"):
        await provider.chat_completion(**_request())
    assert tracker._reserved_usd == 0
    assert tracker.summary()["total_calls"] == 0


@pytest.mark.asyncio
async def test_unbudgeted_unknown_model_is_allowed_and_recorded():
    inner = AsyncMock()
    inner.chat_completion.return_value = _response(cost_usd=0, model="vendor/unknown")
    tracker = CostTracker()
    provider = BudgetedProvider(inner, tracker)

    await provider.chat_completion(**_request("vendor/unknown"))

    inner.chat_completion.assert_awaited_once()
    assert tracker.summary()["total_calls"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["tools", "response_format"])
async def test_token_bearing_request_fields_are_included_in_reservation(field):
    inner = AsyncMock()
    provider = BudgetedProvider(inner, CostTracker(budget_cap_usd=0.001))
    request = {
        "messages": [{"role": "user", "content": "x"}],
        "model": "openai/gpt-4o",
        "role": ModelRole.TARGET,
        "max_tokens": 1,
        field: {"schema": "x" * 4000},
    }

    with pytest.raises(BudgetExhaustedError):
        await provider.chat_completion(**request)

    inner.chat_completion.assert_not_awaited()
