"""Provider factory: creates LLMProvider instances from config.

Routes provider creation by name, validates required API keys,
and returns typed LLMProvider instances backed by the OpenAI SDK.
"""

from __future__ import annotations

from api.config.models import GeneConfig
from api.exceptions import ConfigError
from api.gateway.litellm_provider import LiteLLMProvider
from api.gateway.protocol import LLMProvider
from api.gateway.registry import SUPPORTED_PROVIDERS, get_provider_config


def create_provider(
    provider_name: str,
    config: GeneConfig,
    concurrency_limit: int | None = None,
) -> LLMProvider:
    """Create an LLMProvider instance based on provider name.

    Uses the OpenAI SDK with provider-specific base_url. All providers
    share the same LiteLLMProvider implementation — only the base_url
    and API key differ.

    Args:
        provider_name: Provider identifier ("gemini", "openrouter", "openai").
        config: GeneConfig with API keys and concurrency settings.
        concurrency_limit: Override for concurrency limit (defaults to config value).

    Returns:
        An LLMProvider instance (LiteLLMProvider).

    Raises:
        ConfigError: If provider_name is unknown or required API key is missing.
    """
    limit = concurrency_limit or config.concurrency_limit

    try:
        cfg = get_provider_config(provider_name)
    except ValueError as exc:
        raise ConfigError(
            f"Unknown provider: '{provider_name}'. Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        ) from exc

    api_key = getattr(config, cfg.api_key_field, None)
    if api_key is None:
        env_var = f"GENE_{cfg.api_key_field.upper()}"
        raise ConfigError(
            f"{cfg.api_key_field} is required when using the '{provider_name}' provider. "
            f"Set via {env_var} env var or in the Settings UI"
        )

    return LiteLLMProvider(
        provider=provider_name,
        api_key=api_key,
        concurrency_limit=limit,
    )
