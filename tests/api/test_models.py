"""Tests for GET /api/models endpoint.

Tests cover routing dispatch, API key validation (503), unknown provider (400),
upstream error handling (502), and successful model listing for both providers.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from api.web.app import create_app
from api.web.deps import get_config
from api.web.event_bus import EventBus
from api.web.run_manager import RunManager
from api.config.models import GeneConfig
from api.gateway.model_listing import ModelInfo, clear_model_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear model cache before each test."""
    clear_model_cache()
    yield
    clear_model_cache()


def _make_app_with_config(**config_kwargs) -> FastAPI:
    """Create a test FastAPI app with custom GeneConfig overrides."""
    application = create_app()
    test_config = GeneConfig(
        **config_kwargs,
    )
    application.dependency_overrides[get_config] = lambda: test_config
    application.state.run_manager = RunManager()
    application.state.event_bus = EventBus()
    return application


@pytest.fixture
def app_with_keys():
    """App with fake API keys configured for both providers."""
    return _make_app_with_config(
        openrouter_api_key="fake-or-key",
        gemini_api_key="fake-gemini-key",
    )


@pytest.fixture
def app_no_keys():
    """App with no API keys configured (explicitly None)."""
    return _make_app_with_config(
        openrouter_api_key=None,
        gemini_api_key=None,
    )


@pytest.fixture
async def client_with_keys(app_with_keys: FastAPI):
    """Async HTTP client with API keys configured."""
    transport = httpx.ASGITransport(app=app_with_keys)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def client_no_keys(app_no_keys: FastAPI):
    """Async HTTP client with no API keys configured."""
    transport = httpx.ASGITransport(app=app_no_keys)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


_SAMPLE_OPENROUTER_MODELS = [
    ModelInfo(
        id="openai/gpt-4o-mini",
        name="OpenAI: GPT-4o Mini",
        context_length=128000,
        input_price_per_mtok=0.15,
        output_price_per_mtok=0.6,
        provider="openrouter",
    ),
    ModelInfo(
        id="anthropic/claude-sonnet-4",
        name="Anthropic: Claude Sonnet 4",
        context_length=200000,
        input_price_per_mtok=3.0,
        output_price_per_mtok=15.0,
        provider="openrouter",
    ),
]

_SAMPLE_GEMINI_MODELS = [
    ModelInfo(
        id="gemini-2.5-pro",
        name="Gemini 2.5 Pro",
        context_length=1048576,
        provider="gemini",
    ),
]


class TestListModelsSuccess:
    """Tests for successful model listing."""

    @patch("api.web.routers.models._get_cached_or_fetch")
    async def test_list_openrouter_models_success(self, mock_fetch, client_with_keys):
        """GET /api/models?provider=openrouter returns 200 with model list."""
        mock_fetch.return_value = _SAMPLE_OPENROUTER_MODELS

        resp = await client_with_keys.get("/api/models/", params={"provider": "openrouter"})

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["id"] == "openai/gpt-4o-mini"
        assert data[0]["input_price_per_mtok"] == pytest.approx(0.15)
        assert data[0]["provider"] == "openrouter"

    @patch("api.web.routers.models._get_cached_or_fetch")
    async def test_list_gemini_models_success(self, mock_fetch, client_with_keys):
        """GET /api/models?provider=gemini returns 200 with model list."""
        mock_fetch.return_value = _SAMPLE_GEMINI_MODELS

        resp = await client_with_keys.get("/api/models/", params={"provider": "gemini"})

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "gemini-2.5-pro"
        assert data[0]["provider"] == "gemini"
        assert data[0]["input_price_per_mtok"] is None


class TestListModelsErrors:
    """Tests for error responses."""

    async def test_unknown_provider_returns_400(self, client_with_keys):
        """GET /api/models?provider=anthropic returns 400."""
        resp = await client_with_keys.get("/api/models/", params={"provider": "anthropic"})

        assert resp.status_code == 400
        assert "Unknown provider" in resp.json()["detail"]

    async def test_missing_openrouter_key_returns_503(self, client_no_keys):
        """GET /api/models?provider=openrouter returns 503 when key is None."""
        resp = await client_no_keys.get("/api/models/", params={"provider": "openrouter"})

        assert resp.status_code == 503
        assert "API key not configured" in resp.json()["detail"]

    async def test_missing_gemini_key_returns_503(self, client_no_keys):
        """GET /api/models?provider=gemini returns 503 when key is None."""
        resp = await client_no_keys.get("/api/models/", params={"provider": "gemini"})

        assert resp.status_code == 503
        assert "API key not configured" in resp.json()["detail"]

    @patch("api.web.routers.models._get_cached_or_fetch")
    async def test_upstream_error_returns_502(self, mock_fetch, client_with_keys):
        """Upstream API errors are returned as 502."""
        mock_fetch.side_effect = httpx.HTTPStatusError(
            "Internal Server Error",
            request=httpx.Request("GET", "http://upstream"),
            response=httpx.Response(500),
        )

        resp = await client_with_keys.get("/api/models/", params={"provider": "openrouter"})

        assert resp.status_code == 502
        assert "Upstream" in resp.json()["detail"]
