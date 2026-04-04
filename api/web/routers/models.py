"""Models router -- proxy endpoint for provider model listings.

Provides GET /api/models?provider=X which fetches and returns normalized
model metadata from upstream provider APIs with 5-minute TTL caching.

The frontend calls this endpoint instead of provider APIs directly to
avoid exposing API keys in the browser network tab.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from api.config.models import GeneConfig
from api.gateway.model_listing import (
    ModelInfo,
    _get_cached_or_fetch,
    fetch_gemini_models,
    fetch_openai_models,
    fetch_openrouter_models,
)
from api.storage.models import User
from api.web.auth import get_current_user
from api.web.deps import get_config

router = APIRouter()

# Provider -> (config key field, display name, fetcher function)
_PROVIDER_CONFIG: dict[str, tuple[str, str, object]] = {
    "openrouter": ("openrouter_api_key", "OpenRouter", fetch_openrouter_models),
    "gemini": ("gemini_api_key", "Gemini", fetch_gemini_models),
    "openai": ("openai_api_key", "OpenAI", fetch_openai_models),
}


@router.get("/", response_model=list[ModelInfo])
async def list_models(
    provider: str = Query(..., description="Provider name: 'openrouter', 'gemini', or 'openai'"),
    config: GeneConfig = Depends(get_config),
    user: User = Depends(get_current_user),
) -> list[ModelInfo]:
    """List available models from the specified provider.

    Returns cached results if a successful fetch occurred within the
    last 5 minutes.  Missing API keys return 503; unknown providers
    return 400; upstream failures return 502.
    """
    provider_info = _PROVIDER_CONFIG.get(provider)
    if provider_info is None:
        supported = ", ".join(sorted(_PROVIDER_CONFIG.keys()))
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider}. Supported: {supported}",
        )

    key_field, display_name, fetcher_fn = provider_info
    api_key = getattr(config, key_field, None)
    if api_key is None:
        raise HTTPException(
            status_code=503,
            detail=f"{display_name} API key not configured",
        )

    fetcher = lambda: fetcher_fn(api_key)  # noqa: E731

    try:
        return await _get_cached_or_fetch(provider, fetcher)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Upstream {provider} API error: {exc.response.status_code}",
        ) from exc
