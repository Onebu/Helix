"""Integration tests for unified provider client configuration.

Verifies that each provider (gemini, openrouter, openai) can be independently
created via the factory with correct base_url, api_key, and headers.
Tests that the unified client dispatches to the correct provider endpoint
based on registry configuration.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.config.models import GeneConfig
from api.exceptions import ConfigError
from api.gateway.factory import create_provider
from api.gateway.litellm_provider import LiteLLMProvider
from api.gateway.protocol import LLMProvider
from api.gateway.registry import PROVIDER_REGISTRY
from api.types import ModelRole


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def all_keys_config() -> GeneConfig:
    """GeneConfig with all 3 provider API keys set."""
    return GeneConfig(
        gemini_api_key="test-gemini-key",
        openrouter_api_key="test-openrouter-key",
        openai_api_key="test-openai-key",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProviderIntegration:
    """Per-provider configuration and call verification tests."""

    # -- Test 1-3: create_provider returns correct LiteLLMProvider per provider --

    @pytest.mark.parametrize("provider_name", ["gemini", "openrouter", "openai"])
    def test_create_provider_returns_litellm_provider(
        self, all_keys_config: GeneConfig, provider_name: str
    ):
        """create_provider returns LiteLLMProvider with correct _provider field."""
        provider = create_provider(provider_name, all_keys_config)
        assert isinstance(provider, LiteLLMProvider)
        assert provider._provider == provider_name

    # -- Test 4: All 3 providers satisfy LLMProvider protocol --

    @pytest.mark.parametrize("provider_name", ["gemini", "openrouter", "openai"])
    def test_provider_satisfies_protocol(self, all_keys_config: GeneConfig, provider_name: str):
        """Each provider satisfies the LLMProvider runtime_checkable Protocol."""
        provider = create_provider(provider_name, all_keys_config)
        assert isinstance(provider, LLMProvider)

    # -- Test 5: Each provider's AsyncOpenAI client has correct base_url --

    @pytest.mark.parametrize("provider_name", ["gemini", "openrouter", "openai"])
    def test_provider_client_base_url_matches_registry(
        self, all_keys_config: GeneConfig, provider_name: str
    ):
        """Internal AsyncOpenAI client base_url matches PROVIDER_REGISTRY."""
        provider = create_provider(provider_name, all_keys_config)
        expected_url = PROVIDER_REGISTRY[provider_name].base_url
        # AsyncOpenAI.base_url is an httpx.URL; compare string representation
        assert str(provider._client.base_url).rstrip("/") == expected_url.rstrip("/")

    # -- Test 6: OpenRouter provider has HTTP-Referer and X-Title headers --

    def test_openrouter_default_headers(self, all_keys_config: GeneConfig):
        """OpenRouter provider's client has HTTP-Referer and X-Title headers."""
        provider = create_provider("openrouter", all_keys_config)
        # AsyncOpenAI stores default_headers in _custom_headers
        headers = provider._client._custom_headers
        assert "HTTP-Referer" in headers
        assert headers["HTTP-Referer"] == "https://github.com/gene-prompter"
        assert "X-Title" in headers
        assert headers["X-Title"] == "Helix"

    # -- Test 7: Unknown provider raises ConfigError --

    def test_unknown_provider_raises_config_error(self, all_keys_config: GeneConfig):
        """create_provider with unknown provider name raises ConfigError."""
        with pytest.raises(ConfigError, match="Unknown provider"):
            create_provider("unknown_provider", all_keys_config)

    # -- Test 8: Missing API key raises ConfigError with helpful message --

    def test_missing_api_key_raises_config_error(self):
        """create_provider with missing API key raises ConfigError with env var hint."""
        config_no_keys = GeneConfig()
        with pytest.raises(ConfigError, match="is required when using"):
            create_provider("gemini", config_no_keys)

    # -- Test 9: chat_completion dispatches to the correct provider's SDK client --

    @pytest.mark.parametrize("provider_name", ["gemini", "openrouter", "openai"])
    async def test_chat_completion_dispatches_to_correct_client(
        self, all_keys_config: GeneConfig, provider_name: str
    ):
        """chat_completion dispatches through the provider's internal SDK client."""
        provider = create_provider(provider_name, all_keys_config)

        # Mock the internal SDK client's chat.completions.create
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "test response"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_response.model = "mock-model"
        mock_response.id = "mock-id"

        provider._client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await provider.chat_completion(
            messages=[{"role": "user", "content": "Hello"}],
            model="mock-model",
            role=ModelRole.TARGET,
        )

        # Verify the SDK client was called (proving dispatch to correct provider)
        provider._client.chat.completions.create.assert_called_once()
        assert result.content == "test response"
        assert result.role == ModelRole.TARGET
