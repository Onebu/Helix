"""LLM provider wrapper that reserves budget and owns call accounting."""

from __future__ import annotations

import asyncio
from typing import Any

from api.gateway.cost import CostTracker
from api.gateway.protocol import LLMProvider
from api.types import LLMResponse, ModelRole

_TOKEN_BEARING_KWARGS = ("tools", "response_format")


class BudgetedProvider:
    """Reserve and account for calls while optionally owning the inner lifecycle.

    Entering this wrapper enters and closes the inner provider. In evolution runs,
    the inner provider is entered first and its surrounding exit stack owns closure;
    the wrapper is then used only for calls.
    """

    owns_cost_accounting = True

    def __init__(self, inner: LLMProvider, cost_tracker: CostTracker) -> None:
        self._inner = inner
        self._cost_tracker = cost_tracker

    @property
    def cost_tracker(self) -> CostTracker:
        """The tracker that exclusively accounts for this wrapper's calls."""
        return self._cost_tracker

    async def chat_completion(
        self,
        messages: list[dict],
        model: str,
        role: ModelRole,
        **kwargs: Any,
    ) -> LLMResponse:
        input_parts: list[Any] = list(messages)
        input_parts.extend(
            kwargs[field]
            for field in _TOKEN_BEARING_KWARGS
            if kwargs.get(field) is not None
        )
        input_tokens = max(1, sum(len(str(part)) for part in input_parts) // 4)
        for field in ("max_tokens", "max_completion_tokens"):
            value = kwargs.get(field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"{field} must be a positive integer")
        output_tokens = (
            kwargs.get("max_tokens")
            if kwargs.get("max_tokens") is not None
            else kwargs.get("max_completion_tokens")
        )
        if output_tokens is None:
            output_tokens = 4096
        reservation = await self._cost_tracker.reserve(model, input_tokens, output_tokens)
        response: LLMResponse | None = None
        try:
            response = await self._inner.chat_completion(
                messages=messages,
                model=model,
                role=role,
                **kwargs,
            )
            return response
        finally:
            cleanup = asyncio.create_task(self._cost_tracker.reconcile(reservation, response))
            cancellation: asyncio.CancelledError | None = None
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError as exc:
                    cancellation = exc
            cleanup.result()
            if cancellation is not None:
                raise cancellation

    async def close(self) -> None:
        await self._inner.close()

    async def __aenter__(self):
        entered = await self._inner.__aenter__()
        self._inner = entered
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return await self._inner.__aexit__(exc_type, exc_val, exc_tb)
